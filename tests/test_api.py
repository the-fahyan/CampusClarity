"""API integration tests: contracts, statuses, error taxonomy (DESIGN.md §8, §6.8)."""
from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

from backend.main import create_app
from backend.retrieval import RetrievalIndex
from tests.conftest import build_tiny_index, make_settings


def test_health_shape(client: TestClient):
    body = client.get("/api/health").json()
    assert body["index_ready"] is True
    assert body["llm_mode"] == "mock"
    assert body["status"] == "degraded"  # mock ⇒ degraded by design (§5.5)
    assert set(body) >= {"status", "index_ready", "chunk_count", "source_count", "llm_mode", "model", "version"}


def test_ask_answered_mock_with_citations(client: TestClient):
    r = client.post("/api/ask", json={"question": "single occupancy hostel fee"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "answered"
    assert body["citations"], "answered must carry >=1 citation (FR-04)"
    c = body["citations"][0]
    assert {"citation_id", "chunk_id", "source_title", "page", "snippet", "score", "is_sample"} <= set(c)
    assert r.headers.get("X-Request-ID")
    assert body["request_id"]


def test_ask_422_empty_and_too_long(client: TestClient):
    assert client.post("/api/ask", json={"question": ""}).status_code == 422
    assert client.post("/api/ask", json={"question": "ab"}).status_code == 422
    assert client.post("/api/ask", json={"question": "x" * 501}).status_code == 422
    body = client.post("/api/ask", json={"question": ""}).json()
    assert body["status"] == "validation_error"
    assert body["request_id"]


def test_refusal_has_no_citations(tmp_index: RetrievalIndex, tmp_path):
    # Force layer-1 refusal with an unreachable threshold.
    settings = make_settings(BM25_MIN_SCORE=10_000.0)
    app = create_app(settings=settings, index=tmp_index)
    with TestClient(app) as c:
        body = c.post("/api/ask", json={"question": "single occupancy hostel fee"}).json()
    assert body["status"] == "insufficient_knowledge"
    assert body["citations"] == []


def test_rate_limit_returns_429(tmp_index: RetrievalIndex):
    settings = make_settings(RATE_LIMIT_PER_MINUTE=3)
    app = create_app(settings=settings, index=tmp_index)
    with TestClient(app) as c:
        codes = [c.post("/api/ask", json={"question": "hostel fee"}).status_code for _ in range(4)]
    assert codes[:3] == [200, 200, 200]
    assert codes[3] == 429
    body = c.post("/api/ask", json={"question": "hostel fee"}).json()
    assert body["status"] == "rate_limited"


def test_upstream_failure_returns_502(tmp_index: RetrievalIndex):
    def failing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    settings = make_settings(
        MOCK_LLM=False,
        GEMINI_API_KEY="test_key",
        BM25_MIN_SCORE=0.0,  # ensure the gate passes so the model is called
        GEMMA_MODEL_ID="m1",
        GEMMA_FALLBACK_MODEL_ID="m2",
    )
    import backend.generator as gen_mod

    orig_sleep = gen_mod.time.sleep
    gen_mod.time.sleep = lambda *_: None
    try:
        app = create_app(settings=settings, index=tmp_index, transport=httpx.MockTransport(failing))
        with TestClient(app, raise_server_exceptions=False) as c:
            r = c.post("/api/ask", json={"question": "single occupancy hostel fee"})
    finally:
        gen_mod.time.sleep = orig_sleep
    assert r.status_code == 502
    body = r.json()
    assert body["status"] == "upstream_error"
    assert body["request_id"]
    assert "Traceback" not in r.text


def test_health_degraded_when_index_missing(tmp_path):
    settings = make_settings(INDEX_DIR=str(tmp_path / "empty"), SOURCES_DIR=str(tmp_path / "src"))
    (tmp_path / "empty").mkdir()
    (tmp_path / "src").mkdir()
    app = create_app(settings=settings, index=None, index_dir=tmp_path / "empty")
    with TestClient(app) as c:
        body = c.get("/api/health").json()
    assert body["index_ready"] is False
    assert body["status"] == "degraded"
    assert body["chunk_count"] == 0


def test_kb_unavailable_returns_503(tmp_path):
    settings = make_settings(INDEX_DIR=str(tmp_path / "empty"), SOURCES_DIR=str(tmp_path / "src"))
    (tmp_path / "empty").mkdir()
    (tmp_path / "src").mkdir()
    app = create_app(settings=settings, index=None, index_dir=tmp_path / "empty")
    with TestClient(app) as c:
        r = c.post("/api/ask", json={"question": "hostel fee"})
    assert r.status_code == 503
    assert r.json()["status"] == "kb_unavailable"


def test_sources_shape_and_how_to_add(client: TestClient):
    body = client.get("/api/sources").json()
    assert body["how_to_add"]
    assert len(body["sources"]) == 2
    sample = [s for s in body["sources"] if s["is_sample"]]
    assert sample and sample[0]["title"] == "Sample Notice"
    assert all({"source_id", "title", "type", "is_sample", "chunk_count", "file"} <= set(s) for s in body["sources"])
