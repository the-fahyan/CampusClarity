"""FastAPI application: routes, middleware, static mount, exception handlers.

Responsibility (DESIGN.md §1.2, §6.8, §8): expose `POST /api/ask`,
`GET /api/health`, `GET /api/sources`, serve `frontend/`, and map every failure to
a sanitized error body. Delegates business logic to `service.py`.
"""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.config import ConfigError, Settings, get_settings
from backend.generator import Generator, UpstreamError
from backend.prompts import ERROR_MESSAGE
from backend.ratelimit import RateLimiter
from backend.retrieval import (
    KnowledgeBaseError,
    RetrievalIndex,
    index_ready,
    load_index,
    reset_index,
)
from backend.schemas import (
    AskRequest,
    ErrorResponse,
    HealthResponse,
    SourceInfo,
    SourcesResponse,
)
from backend.service import AnswerService

logger = logging.getLogger("campusmate")

HOW_TO_ADD = (
    "Add an approved .txt file to data/sources/, register it in manifest.json, "
    "run python scripts/ingest.py, then re-run scripts/run_battery.py."
)


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _client_ip(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def read_manifest(sources_dir: Path) -> list[dict]:
    """Read manifest entries for the sources endpoint (display only)."""
    path = Path(sources_dir) / "manifest.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return list(data.get("sources", []))


def create_app(
    settings: Settings | None = None,
    index: RetrievalIndex | None = None,
    index_dir: Path | None = None,
    transport=None,
) -> FastAPI:
    settings = settings or get_settings()
    _configure_logging(settings.LOG_LEVEL)

    app = FastAPI(
        title="CampusMate AI",
        version=settings.APP_VERSION,
        description="Independent, source-grounded campus Q&A assistant (prototype).",
    )

    # --- Load index (missing ⇒ degraded, clear log) --- #
    if index is None:
        try:
            index = load_index(index_dir or Path(settings.INDEX_DIR))
        except KnowledgeBaseError as exc:
            logger.warning("index not loaded: %s", exc)
            index = None

    app.state.settings = settings
    app.state.index = index
    app.state.generator = Generator(settings, transport=transport)
    app.state.limiter = RateLimiter(settings.RATE_LIMIT_PER_MINUTE)

    def _service() -> AnswerService | None:
        if app.state.index is None:
            return None
        return AnswerService(settings, app.state.index, app.state.generator)

    # --- request_id middleware --- #
    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        request.state.request_id = uuid.uuid4().hex
        # Body-size guard (NFR-03): reject oversize bodies early.
        try:
            length = int(request.headers.get("content-length", "0") or 0)
        except ValueError:
            length = 0
        if length > settings.MAX_BODY_BYTES:
            return _error(
                request,
                413,
                "validation_error",
                "Request body is too large.",
            )
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    # --- error handlers --- #
    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError):
        return _error(
            request,
            422,
            "validation_error",
            "The question must be between 3 and 500 characters.",
            detail=exc.errors(),
        )

    @app.exception_handler(UpstreamError)
    async def _upstream_handler(request: Request, exc: UpstreamError):
        logger.error("rid=%s upstream_error: %s", _rid(request), exc)
        return _error(
            request,
            502,
            "upstream_error",
            "The assistant could not reach the language model. Please try again.",
        )

    @app.exception_handler(KnowledgeBaseError)
    async def _kb_handler(request: Request, exc: KnowledgeBaseError):
        logger.error("rid=%s kb_unavailable: %s", _rid(request), exc)
        return _error(
            request,
            503,
            "kb_unavailable",
            "Knowledge base is being built. Run python scripts/ingest.py.",
        )

    @app.exception_handler(Exception)
    async def _unhandled_handler(request: Request, exc: Exception):
        logger.exception("rid=%s internal_error: %s", _rid(request), exc)
        return _error(request, 500, "internal_error", ERROR_MESSAGE)

    # --- routes --- #
    @app.post("/api/ask")
    async def ask(request: Request, body: AskRequest):
        rid = _rid(request)
        limiter: RateLimiter = app.state.limiter
        ip = _client_ip(request)
        if not limiter.allow(ip):
            logger.info("rid=%s route=/api/ask status=rate_limited ip=%s", rid, ip)
            resp = _error(
                request, 429, "rate_limited", "Too many requests — please wait a moment."
            )
            resp.headers["Retry-After"] = str(limiter.retry_after(ip))
            return resp

        service = _service()
        if service is None:
            raise KnowledgeBaseError("index not loaded")

        try:
            result = service.ask(body.question, rid)
        except UpstreamError as exc:
            logger.info(
                "rid=%s route=/api/ask status=upstream_error error=%s", rid, exc
            )
            return _error(
                request,
                502,
                "upstream_error",
                "The assistant could not reach the language model. Please try again.",
            )

        _log_request(
            settings,
            rid,
            result.status,
            result.latency_ms,
            result.retrieval.top_score,
            result.model.name,
            body.question,
        )
        return result

    @app.get("/api/health", response_model=HealthResponse)
    async def health():
        ready = index_ready(Path(settings.INDEX_DIR))
        chunk_count = app.state.index.chunk_count if app.state.index else 0
        source_count = len(read_manifest(Path(settings.SOURCES_DIR)))
        status = "ok" if (ready and not settings.MOCK_LLM) else "degraded"
        return HealthResponse(
            status=status,
            index_ready=ready,
            chunk_count=chunk_count,
            source_count=source_count,
            llm_mode=settings.llm_mode,  # type: ignore[arg-type]
            model=settings.GEMMA_MODEL_ID,
            version=settings.APP_VERSION,
        )

    @app.get("/api/sources", response_model=SourcesResponse)
    async def sources():
        entries = read_manifest(Path(settings.SOURCES_DIR))
        index = app.state.index
        infos: list[SourceInfo] = []
        for entry in entries:
            sid = entry.get("source_id")
            chunk_pages: set[int] = set()
            count = 0
            if index is not None:
                for chunk in index.chunks:
                    if chunk["source_id"] == sid:
                        count += 1
                        chunk_pages.update(
                            range(chunk["page_start"], chunk["page_end"] + 1)
                        )
            infos.append(
                SourceInfo(
                    source_id=str(sid),
                    title=str(entry.get("title", sid)),
                    type=str(entry.get("type", "unknown")),
                    verified=bool(entry.get("verified", False)),
                    is_sample=bool(entry.get("is_sample", False)),
                    file=str(entry.get("file", "")),
                    chunk_count=count,
                    pages=len(chunk_pages),
                )
            )
        return SourcesResponse(sources=infos, how_to_add=HOW_TO_ADD)

    # --- static frontend (mounted AFTER API routes so /api/* wins) --- #
    frontend_dir = Path(settings.FRONTEND_DIR)
    if frontend_dir.exists():
        app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")

    return app


def _rid(request: Request) -> str:
    return getattr(request.state, "request_id", "-")


def _error(
    request: Request,
    status_code: int,
    status: str,
    message: str,
    detail: object | None = None,
) -> JSONResponse:
    body: dict = {
        "request_id": _rid(request),
        "status": status,
        "message": message,
    }
    if detail is not None:
        body["detail"] = detail
    return JSONResponse(status_code=status_code, content=body)


def _log_request(
    settings: Settings,
    rid: str,
    status: str,
    latency_ms: int,
    top_score: float,
    model: str,
    question: str,
) -> None:
    """Structured single-line request log (DESIGN.md §12.6, FR-20, NFR-04)."""
    line = (
        f"rid={rid} route=/api/ask status={status} latency_ms={latency_ms} "
        f"top_score={top_score:.4f} model={model}"
    )
    if settings.LOG_LEVEL == "DEBUG":
        line += f' question="{question[:120]}"'
    logger.info(line)


# Module-level app for `uvicorn backend.main:app`.
try:
    app = create_app()
except ConfigError as exc:  # pragma: no cover - startup misconfiguration
    raise SystemExit(f"Configuration error: {exc}") from exc


def reset_for_tests() -> None:
    """Helper used by tests to drop the cached index."""
    reset_index()
