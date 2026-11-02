import time



from typing import Iterator

from chatbot.config import Settings
from openai import OpenAI
import logging
from pydantic import Secret, BaseModel

logger = logging.getLogger(__name__)

from dataclasses import dataclass


class ChatResult(BaseModel):
    content: str
    message: dict
    finish_reason: str | None = None

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cache_hit_tokens: int | None = None
    total_tokens: int | None = None

    latency: float
    ttft: float | None = None
    cost: float | None = None


@dataclass
class Ledger:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_hit_tokens: int = 0
    cost: float = 0.0

    # 记录统计数据缺失的次数
    usage_unavailable_calls: int = 0
    cost_unavailable_calls: int = 0

    def add(self, result: ChatResult) -> None:
        self.calls += 1

        if result.prompt_tokens is None or result.completion_tokens is None:
            self.usage_unavailable_calls += 1
        else:
            self.prompt_tokens += result.prompt_tokens
            self.completion_tokens += result.completion_tokens

        if result.cache_hit_tokens is not None:
            self.cache_hit_tokens += result.cache_hit_tokens

        if result.cost is not None:
            self.cost += result.cost
        else:
            self.cost_unavailable_calls += 1

class LLMClient:
    def __init__(self , settings: Settings):
        self.model = settings.llm_model
        self.extra_body = settings.llm_extra_body
        self.price = settings.llm_price
        self.client = OpenAI(
            api_key= settings.llm_api_key.get_secret_value(),
            base_url= settings.llm_base_url,
            timeout=60.0,
            max_retries=3
        )
        self.last_result: ChatResult |None=None
        self.ledger= Ledger()


    def chat(self,messages: list[dict] , max_tokens: int=500) ->ChatResult:
        start = time.perf_counter()

        response = self.client.chat.completions.create(
            model=self.model,
            messages= messages,
            max_tokens = max_tokens,
            extra_body=self.extra_body
        )
        latency = time.perf_counter()-start
        choice = response.choices[0]
        finish = choice.finish_reason
        if finish == "length":
            logger.warning("模型输出达到 Token 长度限制")
        message = choice.message
        usage = response.usage
        prompt_tokens = usage.prompt_tokens if usage else None
        completion_tokens = usage.completion_tokens if usage else None
        total_tokens = usage.total_tokens if usage else None
        cache_hit_tokens = None
        cost = None
        if usage is not None:
            cache_hit_tokens = getattr(
                usage, "prompt_cache_hit_tokens", None
            )

            if cache_hit_tokens is None:
                details = getattr(usage, "prompt_tokens_details", None)
                cache_hit_tokens = (
                    getattr(details, "cached_tokens", None)
                    if details else None
                )

            if cache_hit_tokens is not None:
                cache_hit_tokens = min(cache_hit_tokens, prompt_tokens)

                cache_hit_price, cache_miss_price, output_price = self.price

                cache_miss_tokens = prompt_tokens - cache_hit_tokens

                cost = (
                               cache_hit_tokens * cache_hit_price
                               + cache_miss_tokens * cache_miss_price
                               + completion_tokens * output_price
                       ) / 1_000_000

        message_data = message.model_dump(exclude_none=True)
        result = ChatResult(
            content= message.content or "",
            message = message_data,
            finish_reason=finish,
            total_tokens=total_tokens,
            cache_hit_tokens=cache_hit_tokens,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency = latency,
            cost= cost,
        )
        self.ledger.add(result)
        self.last_result = result
        return result

    def stream(
            self,
            messages: list[dict],
            max_tokens: int = 500
    ) -> Iterator[str]:

        start = time.perf_counter()

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens,
            extra_body=self.extra_body,
            stream=True,
            stream_options={"include_usage": True}
        )

        # 初始化流式请求的临时状态
        ttft: float | None = None
        content_parts: list[str] = []
        usage = None
        finish_reason: str | None = None

        for chunk in response:

            # 获取 Token 用量
            if chunk.usage is not None:
                usage = chunk.usage

            # 跳过没有 choices 的 Chunk
            if not chunk.choices:
                continue

            choice = chunk.choices[0]

            # 记录结束原因
            if choice.finish_reason is not None:
                finish_reason = choice.finish_reason

                if finish_reason == "length":
                    logger.warning("模型输出达到 Token 长度限制")

            # 获取当前新增文本
            text = choice.delta.content

            if text:
                # 记录首个文本 Token 的时间
                if ttft is None:
                    ttft = time.perf_counter() - start

                content_parts.append(text)
                yield text

        # 整理完整文本
        content = "".join(content_parts)

        # 计算总耗时
        latency = time.perf_counter() - start

        # 初始化统计结果：没有 usage 就保持 None
        prompt_tokens = None
        completion_tokens = None
        total_tokens = None
        cache_hit_tokens = None
        cost = None

        # 只有获取到 usage 才进行统计
        if usage is not None:

            prompt_tokens = usage.prompt_tokens
            completion_tokens = usage.completion_tokens
            total_tokens = usage.total_tokens

            # 获取缓存命中 Token
            cache_hit_tokens = getattr(
                usage, "prompt_cache_hit_tokens", None
            )

            if cache_hit_tokens is None:
                details = getattr(
                    usage, "prompt_tokens_details", None
                )
                cache_hit_tokens = (
                    getattr(details, "cached_tokens", None)
                    if details else None
                )

            # 有准确的缓存统计才能计算准确费用
            if cache_hit_tokens is not None:
                cache_hit_tokens = min(cache_hit_tokens, prompt_tokens)

                cache_hit_price, cache_miss_price, output_price = self.price

                cache_miss_tokens = prompt_tokens - cache_hit_tokens

                cost = (
                               cache_hit_tokens * cache_hit_price
                               + cache_miss_tokens * cache_miss_price
                               + completion_tokens * output_price
                       ) / 1_000_000

        # 封装最终消息
        message = {
            "role": "assistant",
            "content": content
        }

        # 保存最终结果
        result = ChatResult(
            content=content,
            message=message,
            finish_reason=finish_reason,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cache_hit_tokens=cache_hit_tokens,
            total_tokens=total_tokens,
            cost=cost,
            ttft=ttft,
            latency=latency
        )
        self.last_result = result
        self.ledger.add(result)

