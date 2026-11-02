# agent-60-lab/common/llm.py
"""全课复用的大模型客户端。依赖：uv add openai python-dotenv"""
from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from dataclasses import dataclass
from ftplib import MSG_OOB
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI


@dataclass
class Price:
    """元 / 百万 token：缓存命中输入、未命中输入、输出。"""

    hit: float = 0.0
    miss: float = 0.0
    out: float = 0.0

    @classmethod
    def parse(cls, raw: str | None) -> Price:
        if not raw:
            return cls()
        hit, miss, out = (float(x) for x in raw.split(","))
        return cls(hit, miss, out)


@dataclass
class ChatResult:
    content: str
    reasoning: str | None
    finish_reason: str | None
    message: dict[str, Any]          # 原样追加进历史的 assistant 消息
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_hit_tokens: int = 0
    cost: float = 0.0                # 元
    latency: float = 0.0             # 秒，非流式为总耗时
    ttft: float | None = None        # 秒，只有流式有


@dataclass
class Ledger:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost: float = 0.0

    def add(self, r: ChatResult) -> None:
        self.calls += 1
        self.prompt_tokens += r.prompt_tokens
        self.completion_tokens += r.completion_tokens
        self.cost += r.cost

    def __str__(self) -> str:
        return (f"{self.calls} 次调用 | 输入 {self.prompt_tokens} / 输出 {self.completion_tokens} tokens"
                f" | 约 ¥{self.cost:.4f}")


class LLMClient:
    def __init__(self, env_file: str | None = None, **overrides: Any) -> None:
        if env_file:
            load_dotenv(env_file, override=True)
        else:
            load_dotenv()
        self.model: str = overrides.get("model") or os.environ["LLM_MODEL"]
        self.price = Price.parse(overrides.get("price") or os.environ.get("LLM_PRICE"))
        self.extra_body: dict[str, Any] = json.loads(os.environ.get("LLM_EXTRA_BODY", "{}"))
        self.client = OpenAI(
            base_url=overrides.get("base_url") or os.environ["LLM_BASE_URL"],
            api_key=overrides.get("api_key") or os.environ["LLM_API_KEY"],
            max_retries=overrides.get("max_retries", 3),
            timeout=overrides.get("timeout", 120.0),
        )
        self.ledger = Ledger()

    # ---------- 内部工具 ----------
    def _kwargs(self, messages: list[dict[str, Any]], **kw: Any) -> dict[str, Any]:
        extra = {**self.extra_body, **kw.pop("extra_body", {})}
        args: dict[str, Any] = {"model": kw.pop("model", self.model), "messages": messages, **kw}
        if extra:
            args["extra_body"] = extra
        return args

    def _cost(self, prompt: int, completion: int, hit: int) -> float:
        miss = prompt - hit
        p = self.price
        return (hit * p.hit + miss * p.miss + completion * p.out) / 1_000_000

    @staticmethod
    def _cache_hit(usage: Any) -> int:
        # DeepSeek: prompt_cache_hit_tokens；OpenAI 等：prompt_tokens_details.cached_tokens
        hit = getattr(usage, "prompt_cache_hit_tokens", None)
        if hit is None:
            details = getattr(usage, "prompt_tokens_details", None)
            hit = getattr(details, "cached_tokens", None) if details else None
        return hit or 0

    #----------- 非流式 ----------
    def chat(self,messages:list[dict[str,Any]], **kw: Any) -> ChatResult:
        start = time.perf_counter()
        resp = self.client.chat.completions.create(**self._kwargs(messages,**kw))
        latency = time.perf_counter()-start
        choice = resp.choices[0]
        msg = choice.message.model_dump(exclude_none=True)
        u = resp.usage
        hit = self._cache_hit(u)
        result = ChatResult(
            content=choice.message.content or "",
            reasoning=msg.get("reasoning_content"),
            finish_reason=choice.finish_reason,
            message=msg,
            prompt_tokens=u.prompt_tokens if u else 0,
            cache_hit_tokens=hit,
            cost=self._cost(u.prompt_tokens,u.completion_tokens,hit) if u else 0,
            latency=latency,
        )
        self.ledger.add(result)
        return result

    #------------ 流式 ---------
    def stream(self, messages: list[dict[str, Any]], **kw: Any) -> Iterator[str]:
        args = self._kwargs(messages,**kw)
        args["stream"] = True
        args.setdefault("stream_options", {"include_usage": True})
        start = time.perf_counter()
        ttft: float | None = None
        content: list[str] = []
        reasoning: list[str] = []
        finish_reason: str| None = None
        usage = None
        for chunk in self.client.chat.completions.create(**args):
            if chunk.usage:
                usage = chunk.usage
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta
            r = getattr(delta , "reasoning_content", None)
            if r:
                reasoning.append(r)
            if delta.content:
                if ttft is None:
                    ttft = time.perf_counter()-start
                content.append(delta.content)
                yield delta.content
            if choice.finish_reason:
                finish_reason=choice.finish_reason
        text = "".join(content)
        msg : dict[str , Any] = {"role": "assistant" , "content": text}
        if reasoning:
            msg["reasoning_content"] = "".join(reasoning)
        prompt = usage.prompt_tokens if usage else 0
        completion = usage.completion_tokens if usage else 0
        hit = self._cache_hit(usage) if usage else 0
        self.last = ChatResult(
            content=text,
            reasoning=msg.get("reasoning_content"),
            finish_reason=finish_reason,
            message=msg,
            prompt_tokens=prompt,
            completion_tokens=completion,
            cache_hit_tokens=hit,
            cost=self._cost(prompt, completion, hit),
            latency=time.perf_counter() - start,
            ttft=ttft
        )
        self.ledger.add(self.last)

class Conversation:
    """一个对话的 messages 管理：system 永远保留，历史按「轮」做滑动窗口。"""

    def __init__(self, system: str, max_turns: int = 20) -> None:
        self.system = {"role": "system", "content": system}
        self.turns: list[list[dict[str, Any]]] = []   # 每一轮是一组消息：user + assistant（以后还有 tool）
        self.max_turns = max_turns

    def add_user(self, text: str) -> None:
        self.turns.append([{"role": "user", "content": text}])

    def add_assistant(self, message: dict[str, Any]) -> None:
        self.turns[-1].append(message)

    def messages(self) -> list[dict[str, Any]]:
        kept = self.turns[-self.max_turns:]
        return [self.system] + [m for turn in kept for m in turn]