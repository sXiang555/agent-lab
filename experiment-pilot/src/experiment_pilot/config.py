from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from psycopg.conninfo import make_conninfo


@dataclass(frozen=True)
class Settings:
    state_dir: Path = Path(".state")
    database_url: str = ""
    runs_file: Path | None = None
    demo_auth: bool = True
    production: bool = False
    public_showcase: bool = False
    analyst_token: str = "demo-analyst"
    reviewer_token: str = "demo-reviewer"
    other_token: str = "demo-other"
    model_base_url: str = ""
    model_key: str = ""
    small_model: str = ""
    draft_model: str = ""
    reasoning_effort: str = ""
    embedding_model: str = ""
    rerank_url: str = ""
    rerank_model: str = ""
    rerank_key: str = ""
    # USD per million input/output tokens, by configured model tier.
    small_price: tuple[float, float] | None = None
    draft_price: tuple[float, float] | None = None
    trace_enabled: bool = False
    requests_per_minute: int = 30

    def __post_init__(self) -> None:
        if self.production and (self.demo_auth or not self.database_url):
            raise ValueError("Production requires PostgreSQL and non-demo authentication")
        tokens = [self.analyst_token, self.reviewer_token]
        if self.demo_auth:
            tokens.append(self.other_token)
        if not all(tokens) or len(set(tokens)) != len(tokens):
            raise ValueError("Role tokens must be nonempty and distinct")
        if not self.demo_auth:
            if self.analyst_token == self.reviewer_token or any(
                len(token) < 24 or token.startswith("demo-")
                for token in (self.analyst_token, self.reviewer_token)
            ):
                raise ValueError("Set two distinct non-demo tokens of at least 24 characters")
        if (self.small_model or self.draft_model or self.embedding_model) and not self.model_key:
            raise ValueError("PILOT_MODEL_KEY is required when a remote model is configured")
        if self.reasoning_effort not in {"", "none", "minimal", "low", "medium", "high"}:
            raise ValueError("Unsupported PILOT_REASONING_EFFORT")
        if self.rerank_url and not self.rerank_model:
            raise ValueError("PILOT_RERANK_MODEL is required with PILOT_RERANK_URL")
        if self.requests_per_minute < 1:
            raise ValueError("PILOT_REQUESTS_PER_MINUTE must be positive")

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv(Path.cwd() / ".env")
        demo = os.getenv("PILOT_DEMO_AUTH", "1") == "1"
        runs_file = os.getenv("PILOT_RUNS_FILE", "")
        database_url = os.getenv("PILOT_DATABASE_URL", "")
        db_password = _secret("PILOT_DB_PASSWORD")
        if db_password:
            if not database_url:
                raise ValueError("PILOT_DB_PASSWORD requires PILOT_DATABASE_URL")
            database_url = make_conninfo(database_url, password=db_password)
        return cls(
            state_dir=Path(os.getenv("PILOT_STATE_DIR", ".state")),
            database_url=database_url,
            runs_file=Path(runs_file) if runs_file else None,
            demo_auth=demo,
            production=os.getenv("PILOT_PRODUCTION", "0") == "1",
            public_showcase=os.getenv("PILOT_PUBLIC_SHOWCASE", "0") == "1",
            analyst_token=_secret("PILOT_ANALYST_TOKEN", "demo-analyst" if demo else ""),
            reviewer_token=_secret("PILOT_REVIEWER_TOKEN", "demo-reviewer" if demo else ""),
            model_base_url=os.getenv("PILOT_MODEL_BASE_URL", ""),
            model_key=_secret("PILOT_MODEL_KEY"),
            small_model=os.getenv("PILOT_SMALL_MODEL", ""),
            draft_model=os.getenv("PILOT_DRAFT_MODEL", ""),
            reasoning_effort=os.getenv("PILOT_REASONING_EFFORT", ""),
            embedding_model=os.getenv("PILOT_EMBEDDING_MODEL", ""),
            rerank_url=os.getenv("PILOT_RERANK_URL", ""),
            rerank_model=os.getenv("PILOT_RERANK_MODEL", ""),
            rerank_key=_secret("PILOT_RERANK_KEY"),
            small_price=_price("PILOT_SMALL_PRICE"),
            draft_price=_price("PILOT_DRAFT_PRICE"),
            trace_enabled=os.getenv("PILOT_LANGFUSE", "0") == "1",
            requests_per_minute=int(os.getenv("PILOT_REQUESTS_PER_MINUTE", "30")),
        )


def _secret(name: str, default: str = "") -> str:
    value, filename = os.getenv(name), os.getenv(f"{name}_FILE")
    if filename and value is not None:
        raise ValueError(f"Set only one of {name} and {name}_FILE")
    if not filename:
        return value if value is not None else default
    contents = Path(filename).read_text(encoding="utf-8").strip()
    if not contents:
        raise ValueError(f"{name}_FILE is empty")
    return contents


def _price(name: str) -> tuple[float, float] | None:
    raw = os.getenv(name, "")
    if not raw:
        return None
    input_price, output_price = map(float, raw.split(","))
    if any(not math.isfinite(value) or value < 0 for value in (input_price, output_price)):
        raise ValueError(f"{name} requires finite nonnegative prices")
    return input_price, output_price
