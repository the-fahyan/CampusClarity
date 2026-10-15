/* CampusMate AI — frontend state machine and rendering (DESIGN.md §10–§13).
   Vanilla JS, no build step. Technologies: fetch + AbortController only.
   All untrusted text (model/corpus/citations) is rendered with textContent. */

"use strict";

const DEFAULT_TIMEOUT = 15000;
const HEALTH_INTERVAL = 60000;
const MAX_QUESTION = 500;
const MIN_QUESTION = 3;

const EXAMPLES = [
  "What is the hostel fee for a single occupancy room?",
  "How can I apply for admission online?",
  "Does the university provide a bus facility?",
  "Is there a scholarship for siblings of existing students?",
];

const els = {
  log: document.getElementById("message-log"),
  composer: document.getElementById("composer"),
  textarea: document.getElementById("question"),
  send: document.getElementById("send"),
  charCount: document.getElementById("char-count"),
  composerError: document.getElementById("composer-error"),
  statusDot: document.getElementById("status-dot"),
  statusLabel: document.getElementById("status-label"),
  status: document.getElementById("status"),
  drawer: document.getElementById("sources-drawer"),
  scrim: document.getElementById("drawer-scrim"),
  drawerBody: document.getElementById("drawer-body"),
  drawerHowto: document.getElementById("drawer-howto"),
  sourcesToggle: document.getElementById("sources-toggle"),
  drawerClose: document.getElementById("drawer-close"),
};

const state = {
  messages: [], // {role, ...}
  sending: false,
  lastQuestion: null,
  drawerOpen: false,
};

/* ---------------- API helper ---------------- */
async function fetchJson(path, options = {}, timeout = DEFAULT_TIMEOUT) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const res = await fetch(path, { ...options, signal: controller.signal });
    let body = null;
    try {
      body = await res.json();
    } catch {
      body = null;
    }
    return { ok: res.ok, httpStatus: res.status, body };
  } catch (err) {
    return { ok: false, networkError: true, body: null };
  } finally {
    clearTimeout(timer);
  }
}

/* ---------------- small DOM helpers ---------------- */
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

/* Render answer text, highlighting [n] citation markers without innerHTML. */
function renderAnswerText(text) {
  const p = el("p", "answer-text");
  const parts = String(text).split(/(\[\d+\])/g);
  for (const part of parts) {
    const m = part.match(/^\[(\d+)\]$/);
    if (m) {
      p.appendChild(el("span", "cite-marker", part));
    } else if (part) {
      p.appendChild(document.createTextNode(part));
    }
  }
  return p;
}

/* ---------------- rendering ---------------- */
function renderEmptyState() {
  const wrap = el("div", "empty");
  wrap.appendChild(el("h2", null, "Ask about your campus"));
  wrap.appendChild(
    el("p", null, "I answer only from the campus sources I can see and always cite the page. If I don't know, I'll say so.")
  );
  const examples = el("div", "examples");
  for (const q of EXAMPLES) {
    const btn = el("button", "example", q);
    btn.type = "button";
    btn.addEventListener("click", () => {
      els.textarea.value = q;
      updateCharCount();
      els.textarea.focus();
    });
    examples.appendChild(btn);
  }
  wrap.appendChild(examples);
  return wrap;
}

function renderUserTurn(msg) {
  const turn = el("div", "turn turn--user");
  turn.appendChild(el("div", "bubble bubble--user", msg.text));
  return turn;
}

function renderCitationChip(citation, index) {
  const chip = el("button", "chip");
  chip.type = "button";
  chip.setAttribute("aria-label", `Source ${index + 1}: ${citation.source_title}, page ${citation.page}`);
  chip.appendChild(document.createTextNode(`📄 ${citation.source_title} · `));
  chip.appendChild(el("span", "chip__page", `p.${citation.page}`));
  if (citation.is_sample) {
    chip.appendChild(el("span", "badge badge--sample", "SAMPLE"));
  }
  chip.dataset.snippet = citation.snippet || "";
  chip.dataset.score = citation.score != null ? String(citation.score) : "";
  chip.addEventListener("click", () => togglePopover(chip, citation));
  return chip;
}

let popover = null;
function closePopover() {
  if (popover) {
    popover.remove();
    popover = null;
  }
}
function togglePopover(anchor, citation) {
  const wasOpen = popover && popover.dataset.for === citation.citation_id;
  closePopover();
  if (wasOpen) return;
  const pop = el("div", "popover");
  pop.dataset.for = citation.citation_id;
  pop.appendChild(el("p", "popover__title", `${citation.source_title} (PDF page ${citation.page})`));
  pop.appendChild(el("p", "popover__snippet", citation.snippet || ""));
  if (citation.score != null) {
    pop.appendChild(el("p", "muted", `Relevance score: ${Number(citation.score).toFixed(2)}`));
  }
  document.body.appendChild(pop);
  const rect = anchor.getBoundingClientRect();
  const top = window.scrollY + rect.bottom + 6;
  let left = window.scrollX + rect.left;
  left = Math.min(left, window.scrollX + document.documentElement.clientWidth - pop.offsetWidth - 12);
  pop.style.top = `${top}px`;
  pop.style.left = `${Math.max(8, left)}px`;
  popover = pop;
}
document.addEventListener("click", (e) => {
  if (popover && !popover.contains(e.target) && !e.target.classList.contains("chip")) {
    closePopover();
  }
});

function renderAssistantTurn(msg) {
  const turn = el("div", "turn turn--assistant");
  const status = msg.status;
  const isRefusal = status === "insufficient_knowledge" || status === "model_refusal";

  if (isRefusal) {
    const bubble = el("div", "bubble bubble--refusal");
    bubble.appendChild(el("p", null, msg.answer));
    turn.appendChild(bubble);
    const meta = el("div", "meta-row");
    meta.appendChild(el("span", "badge badge--refusal", "Not in my sources"));
    turn.appendChild(meta);
    return turn;
  }

  const bubble = el("div", "bubble bubble--assistant");
  bubble.appendChild(renderAnswerText(msg.answer));
  turn.appendChild(bubble);

  const meta = el("div", "meta-row");
  meta.appendChild(el("span", "badge badge--grounded", "Grounded answer"));
  if (msg.model && msg.model.mode === "mock") {
    meta.appendChild(el("span", "muted", "sample mode"));
  }
  if (typeof msg.latency_ms === "number") {
    meta.appendChild(el("span", "muted", `${msg.latency_ms} ms`));
  }
  const copy = el("button", "btn btn--ghost", "Copy");
  copy.type = "button";
  copy.style.minHeight = "auto";
  copy.style.padding = "2px 10px";
  copy.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(msg.answer);
      copy.textContent = "Copied";
      setTimeout(() => (copy.textContent = "Copy"), 1500);
    } catch {
      copy.textContent = "Copy failed";
    }
  });
  meta.appendChild(copy);
  turn.appendChild(meta);

  if (msg.citations && msg.citations.length) {
    const chips = el("div", "chips");
    msg.citations.forEach((c, i) => chips.appendChild(renderCitationChip(c, i)));
    turn.appendChild(chips);
  }
  return turn;
}

function renderErrorTurn(msg) {
  const turn = el("div", "turn turn--assistant");
  const bubble = el("div", "bubble bubble--error");
  bubble.appendChild(el("p", null, msg.message));
  turn.appendChild(bubble);
  const meta = el("div", "meta-row");
  meta.appendChild(el("span", "badge badge--error", "Something went wrong"));
  const actions = el("div", "card-actions");
  const retry = el("button", "btn btn--ghost", "Retry");
  retry.type = "button";
  retry.addEventListener("click", () => {
    if (msg.retryQuestion) submitQuestion(msg.retryQuestion);
  });
  actions.appendChild(retry);
  meta.appendChild(actions);
  turn.appendChild(meta);
  return turn;
}

function renderLoading() {
  const turn = el("div", "turn turn--assistant");
  const bubble = el("div", "bubble bubble--assistant");
  const typing = el("div", "typing");
  typing.setAttribute("role", "status");
  typing.appendChild(el("span", "sr-only", "Thinking…"));
  typing.appendChild(el("span", "dot"));
  typing.appendChild(el("span", "dot"));
  typing.appendChild(el("span", "dot"));
  bubble.appendChild(typing);
  turn.appendChild(bubble);
  return turn;
}

function render() {
  const log = els.log;
  log.textContent = "";
  if (state.messages.length === 0 && !state.sending) {
    log.appendChild(renderEmptyState());
    return;
  }
  for (const msg of state.messages) {
    if (msg.role === "user") log.appendChild(renderUserTurn(msg));
    else if (msg.role === "assistant") log.appendChild(renderAssistantTurn(msg));
    else if (msg.role === "error") log.appendChild(renderErrorTurn(msg));
  }
  if (state.sending) log.appendChild(renderLoading());
  scrollToBottom();
}

function scrollToBottom() {
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  window.scrollTo({ top: document.body.scrollHeight, behavior: reduce ? "auto" : "smooth" });
}

/* ---------------- composer ---------------- */
function updateCharCount() {
  els.charCount.textContent = `${els.textarea.value.length}/${MAX_QUESTION}`;
  els.send.disabled = state.sending;
}

function showComposerError(message) {
  if (message) {
    els.composerError.textContent = message;
    els.composerError.hidden = false;
  } else {
    els.composerError.textContent = "";
    els.composerError.hidden = true;
  }
}

function validate(question) {
  if (question.length < MIN_QUESTION) return "Please enter at least 3 characters.";
  if (question.length > MAX_QUESTION) return `Please keep the question under ${MAX_QUESTION} characters.`;
  return null;
}

async function submitQuestion(raw) {
  if (state.sending) return;
  const question = String(raw).trim();
  const err = validate(question);
  if (err) {
    showComposerError(err);
    els.textarea.focus();
    return;
  }
  showComposerError(null);
  state.lastQuestion = question;
  state.messages.push({ role: "user", text: question });
  state.sending = true;
  els.textarea.value = "";
  updateCharCount();
  render();

  const { ok, httpStatus, body, networkError } = await fetchJson("/api/ask", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ question }),
  });

  state.sending = false;

  if (networkError) {
    setStatus("down");
    state.messages.push({
      role: "error",
      message: "I couldn't reach the assistant. Check your connection and try again.",
      retryQuestion: question,
    });
  } else if (httpStatus === 429) {
    state.messages.push({
      role: "error",
      message: (body && body.message) || "Too many requests — please wait a moment.",
      retryQuestion: question,
    });
  } else if (!ok) {
    state.messages.push({
      role: "error",
      message: (body && body.message) || "I couldn't complete that request. Please try again in a moment.",
      retryQuestion: question,
    });
  } else {
    state.messages.push({
      role: "assistant",
      status: body.status,
      answer: body.answer,
      citations: body.citations || [],
      model: body.model,
      latency_ms: body.latency_ms,
    });
    refreshHealth();
  }
  render();
  els.textarea.focus();
}

els.composer.addEventListener("submit", (e) => {
  e.preventDefault();
  submitQuestion(els.textarea.value);
});

els.textarea.addEventListener("input", () => {
  updateCharCount();
  autoGrow();
  if (els.composerError.hidden === false) showComposerError(null);
});

els.textarea.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    submitQuestion(els.textarea.value);
  }
});

function autoGrow() {
  const t = els.textarea;
  t.style.height = "auto";
  t.style.height = `${Math.min(t.scrollHeight, 160)}px`;
}

/* ---------------- health ---------------- */
function setStatus(kind, label) {
  els.statusDot.dataset.state = kind;
  els.statusLabel.textContent = label;
}

async function refreshHealth() {
  const { ok, body, networkError } = await fetchJson("/api/health", {}, 8000);
  if (networkError || !ok || !body) {
    setStatus("down", "Offline");
    return;
  }
  if (body.status === "ok") {
    setStatus("ok", "Ready");
  } else {
    let label = "Degraded";
    if (body.index_ready === false) label = "Knowledge base building";
    else if (body.llm_mode === "mock") label = "Sample mode (mock)";
    setStatus("degraded", label);
  }
}

/* ---------------- sources drawer ---------------- */
async function openDrawer() {
  state.drawerOpen = true;
  els.drawer.hidden = false;
  els.scrim.hidden = false;
  els.sourcesToggle.setAttribute("aria-expanded", "true");
  els.drawerClose.focus();
  renderSources();
}

function closeDrawer() {
  state.drawerOpen = false;
  els.drawer.hidden = true;
  els.scrim.hidden = true;
  els.sourcesToggle.setAttribute("aria-expanded", "false");
  els.sourcesToggle.focus();
}

async function renderSources() {
  els.drawerBody.textContent = "";
  els.drawerBody.appendChild(el("p", "muted", "Loading sources…"));
  const { ok, body } = await fetchJson("/api/sources", {}, 8000);
  els.drawerBody.textContent = "";
  if (!ok || !body) {
    els.drawerBody.appendChild(el("p", "muted", "Could not load sources."));
    return;
  }
  for (const s of body.sources) {
    const item = el("div", "source-item");
    const title = el("p", "source-item__title");
    title.appendChild(document.createTextNode(s.title));
    if (s.is_sample) title.appendChild(el("span", "badge badge--sample", "SAMPLE"));
    else if (s.verified) title.appendChild(el("span", "badge badge--grounded", "Verified"));
    item.appendChild(title);
    item.appendChild(el("p", "source-item__meta", `${s.type} · ${s.chunk_count} chunks · ${s.pages} pages`));
    item.appendChild(el("p", "source-item__meta", s.file));
    els.drawerBody.appendChild(item);
  }
  els.drawerHowto.textContent = body.how_to_add || "";
}

els.sourcesToggle.addEventListener("click", () => (state.drawerOpen ? closeDrawer() : openDrawer()));
els.drawerClose.addEventListener("click", closeDrawer);
els.scrim.addEventListener("click", closeDrawer);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    if (state.drawerOpen) closeDrawer();
    closePopover();
  }
});

/* ---------------- boot ---------------- */
updateCharCount();
render();
refreshHealth();
setInterval(refreshHealth, HEALTH_INTERVAL);
