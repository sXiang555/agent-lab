from __future__ import annotations

import json
from time import perf_counter
from typing import Literal, TypeVar

from openai import OpenAI, OpenAIError
from pydantic import BaseModel

from .config import Settings
from .store import Store

T = TypeVar("T", bound=BaseModel)


class Route(BaseModel):
    category: Literal["guide", "unsupported"]


class Recommendation(BaseModel):
    action: Literal["paired_seeds", "align_controls", "check_evaluator", "inspect_small",
                    "recheck_latency", "trace_memory"]


class ModelGateway:
    def __init__(self, settings: Settings, store: Store) -> None:
        self.settings = settings
        self.store = store
        self.client = (
            OpenAI(api_key=settings.model_key, base_url=settings.model_base_url or None,
                   timeout=15, max_retries=1)
            if settings.small_model or settings.draft_model else None
        )

    def ask(self, review_id: str, turn_id: str, tier: Literal["small", "draft"], stage: str,
            schema: type[T], system: str, data: dict) -> T | None:
        name = self.settings.small_model if tier == "small" else self.settings.draft_model
        prices = self.settings.small_price if tier == "small" else self.settings.draft_price
        if self.client is None or not name:
            return None
        start = perf_counter()
        tokens_in = tokens_out = cost = None
        try:
            response = self.client.chat.completions.create(
                model=name,
                messages=[
                    {"role": "system", "content": system + "\nJSON Schema: " +
                     json.dumps(schema.model_json_schema(), ensure_ascii=False)},
                    {"role": "user", "content": json.dumps(data, ensure_ascii=False)},
                ],
                max_tokens=400,
                response_format={"type": "json_object"},
                **({"reasoning_effort": self.settings.reasoning_effort}
                   if self.settings.reasoning_effort else {}),
            )
            if response.usage:
                tokens_in = response.usage.prompt_tokens
                tokens_out = response.usage.completion_tokens
                if prices:
                    cost = (tokens_in * prices[0] + tokens_out * prices[1]) / 1_000_000
            if not response.choices or response.choices[0].finish_reason != "stop":
                return None
            return schema.model_validate_json(response.choices[0].message.content or "")
        except (ValueError, OpenAIError):
            return None
        finally:
            self.store.record(review_id, turn_id, stage, (perf_counter() - start) * 1000,
                              name, tokens_in, tokens_out, cost)
