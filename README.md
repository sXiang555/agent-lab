# agent-lab

这是我的 Agent / 大模型应用练习记录，按练习主题保留独立代码和依赖配置，方便回看实现过程与复现实验。

## 目录结构

```text
.
├── common/                 # 可复用的大模型客户端练习
├── w1/                     # 基础练习：提问、流式输出、GitHub 仓库统计
├── tests/                  # 根目录练习的测试
├── chatbot/                # 独立的对话应用练习
│   ├── src/chatbot/        # 配置、LLM 客户端、对话历史与流式输出
│   ├── scripts/            # 手动 smoke test
│   └── tests/              # chatbot 测试
├── main.py                 # 根目录练习入口
├── pyproject.toml          # 根目录练习依赖
└── chatbot/pyproject.toml  # chatbot 独立依赖
```

## 练习顺序

1. `w1/ask.py`、`w1/chat_stream.py`：请求模型与流式输出基础。
2. `w1/repo_stats.py`：并发 HTTP 请求、Pydantic 数据校验和失败汇总。
3. `common/llm.py`：整理可复用的大模型客户端与调用统计。
4. `chatbot/`：独立实现配置管理、对话历史、非流式/流式客户端及 smoke test。

## 运行

项目使用 Python 3.13 和 [uv](https://docs.astral.sh/uv/)。根目录练习：

```bash
uv sync
uv run python -m w1.repo_stats
uv run pytest
```

`chatbot/` 是独立项目，在该目录运行：

```bash
cd chatbot
uv sync
uv run pytest
```

模型练习需要在本地 `.env`（或 `chatbot/.env.deepseek`）配置 `LLM_API_KEY`、`LLM_BASE_URL` 和 `LLM_MODEL` 等变量。密钥文件和本地对话记录不会纳入版本控制。
