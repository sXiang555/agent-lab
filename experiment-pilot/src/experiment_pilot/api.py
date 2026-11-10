from __future__ import annotations

import json
import logging
import sqlite3
from collections import defaultdict, deque
from contextlib import ExitStack, asynccontextmanager, closing
from hmac import compare_digest
from threading import Lock
from time import monotonic
from typing import Annotated, Literal

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Path, Request
from fastapi.responses import StreamingResponse
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool, PoolTimeout
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from .catalog import Catalog
from .config import Settings
from .graph import build_graph, comparison_result, run_evidence
from .model import ModelGateway
from .retrieval import Retriever
from .service import Principal, ReviewConflict, ReviewService, stable_id
from .store import DecisionConflict, Store

LOGGER = logging.getLogger(__name__)
ReviewId = Annotated[str, Path(pattern=r"^[a-f0-9]{32}$")]
Identifier = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9_-]{8,64}$")]
Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class TurnInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: Identifier
    question: Question
    request_rerun: bool = Field(default=False, strict=True)


class DecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal_id: Identifier
    approve: bool = Field(strict=True)
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]


class RateLimit:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.history: dict[str, deque] = defaultdict(deque)
        self.lock = Lock()

    def check(self, name: str) -> None:
        now = monotonic()
        with self.lock:
            calls = self.history[name]
            while calls and now - calls[0] >= 60:
                calls.popleft()
            if len(calls) >= self.limit:
                raise HTTPException(429, "请求过于频繁，请稍后再试", headers={"Retry-After": "60"})
            calls.append(now)


def stream(events) -> StreamingResponse:
    def encode(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    def serialize():
        try:
            for event, data in events:
                yield encode(event, data)
        except LookupError:
            yield encode("error", {"code": 404, "message": "复盘或申请不存在"})
        except (DecisionConflict, ReviewConflict) as exc:
            yield encode("error", {"code": 409, "message": str(exc)})
        except PermissionError:
            yield encode("error", {"code": 403, "message": "当前身份无权操作"})
        except Exception:
            LOGGER.exception("Review workflow failed")
            yield encode("error", {"code": 503, "message": "处理失败，可用同一请求编号重试"})
        finally:
            events.close()

    return StreamingResponse(serialize(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no",
    })


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    catalog = Catalog(settings.runs_file)
    showcase = Catalog() if settings.public_showcase else None
    limiter = RateLimit(settings.requests_per_minute)
    principals = {
        settings.analyst_token: Principal("analyst", "detection", "analyst"),
        settings.reviewer_token: Principal("reviewer", "detection", "reviewer"),
    }
    if settings.demo_auth:
        principals[settings.other_token] = Principal("other", "vision-private", "analyst")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.state_dir.mkdir(parents=True, exist_ok=True)
        with ExitStack() as stack:
            store = Store(settings.state_dir / "business.sqlite3", settings.database_url)
            pool = None
            if settings.database_url:
                pool = stack.enter_context(ConnectionPool(
                    settings.database_url, open=False, min_size=1, max_size=4, timeout=5,
                    kwargs={"autocommit": True, "prepare_threshold": None,
                            "row_factory": dict_row, "connect_timeout": 4},
                    check=ConnectionPool.check_connection,
                ))
                pool.wait(timeout=12)
                saver = PostgresSaver(pool)
            else:
                conn = stack.enter_context(closing(sqlite3.connect(
                    settings.state_dir / "checkpoints.sqlite3", check_same_thread=False, timeout=10,
                )))
                saver = SqliteSaver(conn)
            saver.setup()
            tracer = None
            if settings.trace_enabled:
                from langfuse import get_client

                tracer = get_client()
                stack.callback(tracer.flush)
            graph = build_graph(catalog, Retriever(settings), store,
                                ModelGateway(settings, store), saver, tracer)
            app.state.service = ReviewService(graph, store)
            app.state.checkpoint_pool = pool
            yield

    app = FastAPI(
        title="ExperimentPilot", version="0.1.0", lifespan=lifespan,
        docs_url="/docs" if not settings.production else None,
        redoc_url="/redoc" if not settings.production else None,
        openapi_url="/openapi.json" if not settings.production else None,
    )

    def principal(authorization: Annotated[str, Header()] = "") -> Principal:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer":
            for token, identity in principals.items():
                if compare_digest(token.encode(), value.encode()):
                    return identity
        raise HTTPException(401, "缺少有效凭证", headers={"WWW-Authenticate": "Bearer"})

    def analyst(identity: Principal = Depends(principal)) -> Principal:
        if identity.role != "analyst":
            raise HTTPException(403, "需要实验员身份")
        return identity

    def reviewer(identity: Principal = Depends(principal)) -> Principal:
        if identity.role != "reviewer":
            raise HTTPException(403, "需要审批员身份")
        return identity

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "demo_auth": settings.demo_auth,
                "catalog": "custom" if settings.runs_file else "demo",
                "public_showcase": settings.public_showcase,
                "retrieval": "pgvector" if settings.database_url else "in-memory",
                "model": "remote" if settings.draft_model or settings.small_model else "rules"}

    @app.get("/ready")
    def ready(request: Request) -> dict:
        try:
            pool = request.app.state.checkpoint_pool
            if pool is not None:
                with pool.connection(timeout=3) as conn:
                    conn.execute("SELECT 1")
            else:
                request.app.state.service.store.ping()
        except (psycopg.Error, sqlite3.Error, PoolTimeout) as exc:
            raise HTTPException(503, "存储暂不可用") from exc
        return {"status": "ready"}

    @app.get("/showcase/{scenario}")
    def public_example(scenario: Literal["improvement", "split", "missing"]) -> dict:
        if showcase is None:
            raise HTTPException(404, "公开样例未启用")
        # The catalog is independently loaded from packaged fixtures.
        # This path has no graph, remote model, credentials or state writes.
        candidate_id = {"improvement": "DET-002", "split": "DET-003", "missing": "DET-004"}[scenario]
        baseline = showcase.get("detection", "DET-001")
        candidate = showcase.get("detection", candidate_id)
        return {"result": comparison_result(baseline, candidate),
                "evidence": [run_evidence(run) for run in (baseline, candidate)]}

    @app.get("/runs")
    def runs(identity: Principal = Depends(principal)) -> list[dict]:
        return [record.model_dump(mode="json") for record in catalog.list(identity.project)]

    @app.post("/reviews")
    def start(body: TurnInput, request: Request, identity: Principal = Depends(analyst)):
        limiter.check(identity.name)
        review_id = stable_id(identity.project, identity.name, body.request_id)
        return stream(request.app.state.service.turn(
            review_id, identity, body.request_id, body.question, body.request_rerun, create=True,
        ))

    @app.post("/reviews/{review_id}/turns")
    def follow_up(review_id: ReviewId, body: TurnInput, request: Request,
                  identity: Principal = Depends(analyst)):
        limiter.check(identity.name)
        return stream(request.app.state.service.turn(
            review_id, identity, body.request_id, body.question, body.request_rerun, create=False,
        ))

    @app.get("/reviews/{review_id}")
    def status(review_id: ReviewId, request: Request, identity: Principal = Depends(principal)):
        try:
            return request.app.state.service.get(review_id, identity)
        except LookupError as exc:
            raise HTTPException(404, "复盘不存在") from exc

    @app.get("/approvals")
    def approvals(request: Request, identity: Principal = Depends(reviewer)):
        return request.app.state.service.store.pending(identity.project)

    @app.post("/reviews/{review_id}/approval")
    def decide(review_id: ReviewId, body: DecisionInput, request: Request,
               identity: Principal = Depends(reviewer)):
        limiter.check(identity.name)
        return stream(request.app.state.service.decide(
            review_id, identity, body.proposal_id, body.approve, body.reason,
        ))

    return app


app = create_app()
