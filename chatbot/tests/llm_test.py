from random import choices
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from chatbot.config import Settings
from chatbot.llm import LLMClient, ChatResult


def test_chat_returns_chat_result():

    # 1. 创建测试配置
    settings = Settings(
        llm_api_key="test-key",
        llm_base_url="https://api.deepseek.com",
        llm_model="deepseek-flash",
        llm_extra_body=None,
        llm_price=(0.04, 2.0, 8.0)
    )

    # 2. 创建客户端
    client = LLMClient(settings)

    # 3. 模拟模型返回的 message
    mock_message = Mock()
    mock_message.content = "你好"
    mock_message.model_dump.return_value = {
        "role": "assistant",
        "content": "你好"
    }

    # 4. 模拟 Token 用量
    mock_usage = SimpleNamespace(
        prompt_tokens=100,
        completion_tokens=20,
        total_tokens=120,
        prompt_cache_hit_tokens=40,
        prompt_tokens_details=None
    )

    # 5. 模拟模型响应
    mock_choice = SimpleNamespace(
        finish_reason="stop",
        message=mock_message
    )

    mock_response = SimpleNamespace(
        choices=[mock_choice],
        usage=mock_usage
    )

    # 6. 替换真实 SDK 请求
    with patch.object(
        client.client.chat.completions,
        "create",
        return_value=mock_response
    ) as mock_create:

        messages = [
            {"role": "user", "content": "你好"}
        ]

        result = client.chat(messages)

    # 7. 检查返回结果
    assert isinstance(result, ChatResult)

    assert result.content == "你好"
    assert result.message["role"] == "assistant"
    assert result.finish_reason == "stop"

    assert result.prompt_tokens == 100
    assert result.completion_tokens == 20
    assert result.total_tokens == 120
    assert result.cache_hit_tokens == 40

    # 8. 检查费用
    expected_cost = (
        40 * 0.04
        + 60 * 2.0
        + 20 * 8.0
    ) / 1_000_000

    assert result.cost == pytest.approx(expected_cost)

    # 9. 检查 SDK 是否被调用
    mock_create.assert_called_once()


def test_stream_returns_chat_result():

    # 1. 创建测试配置
    settings = Settings(
        llm_api_key="test-key",
        llm_base_url="https://api.deepseek.com",
        llm_model="deepseek-flash",
        llm_extra_body=None,
        llm_price=(0.04, 2.0, 8.0)
    )

    client =  LLMClient(settings)

    #构造stream流的返回消息
    chunk1 = SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content="你好"),
                finish_reason=None
            )
        ],
        usage =None
    )

    chunk2 = SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content=None),
                finish_reason="stop"
            )
        ],
        usage =None
    )

    # 4. 模拟最终 Usage Chunk
    usage = SimpleNamespace(
        prompt_tokens=100,
        completion_tokens=20,
        total_tokens=120,
        prompt_cache_hit_tokens=40,
        prompt_tokens_details=None
    )
    chunk3 = SimpleNamespace(
        choices=[],
        usage = usage
    )

    mock_chunks = [chunk1,chunk2,chunk3]

    with patch.object(
            client.client.chat.completions,
            "create",
            return_value=iter(mock_chunks)
    ) as mock_create:
        messages = [
            {"role": "user", "content": "你好"}
        ]
        # 完整消费生成器
        pieces = list(client.stream(messages))

    # 7. 检查流式文本
    assert pieces == ["你好"]

    # 8. 检查最终结果
    result = client.last_result

    assert isinstance(result, ChatResult)
    assert result.content == "你好"
    assert result.message["role"] == "assistant"
    assert result.finish_reason == "stop"

    # 9. 检查 Token 统计
    assert result.prompt_tokens == 100
    assert result.completion_tokens == 20
    assert result.total_tokens == 120
    assert result.cache_hit_tokens == 40

    # 10. 检查费用
    expected_cost = (
                            40 * 0.04
                            + 60 * 2.0
                            + 20 * 8.0
                    ) / 1_000_000

    assert result.cost == pytest.approx(expected_cost)

    # 11. 检查时间统计
    assert result.ttft is not None
    assert result.latency >= result.ttft

    # 12. 检查 SDK 调用
    mock_create.assert_called_once()
