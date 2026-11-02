# agent-60-lab/w1/chat_stream.py
from common.llm import Conversation, LLMClient
import readline

SYSTEM = "你是云簿 CloudLedger 的在线客服助手。回答简洁，中文，150 字以内。今天是 2026-10-12。"

def main() -> None:
    client = LLMClient()
    conv = Conversation(SYSTEM , max_turns=6)
    while True :
        try:
            text = input("\n你:").strip()
        except EOFError:
            break

        if not text:
            break
        conv.add_user(text)
        print("助手:", end="" , flush=True)

        def check_surrogates(obj, path="root"):
            if isinstance(obj, str):
                for i, char in enumerate(obj):
                    code = ord(char)

                    if 0xD800 <= code <= 0xDFFF:
                        print(f"发现异常字符！")
                        print(f"位置：{path}[{i}]")
                        print(f"编码：U+{code:04X}")
                        print(f"上下文：{obj[max(0, i - 10):i + 10]!r}")

            elif isinstance(obj, dict):
                for key, value in obj.items():
                    check_surrogates(value, f"{path}.{key}")

            elif isinstance(obj, list):
                for i, value in enumerate(obj):
                    check_surrogates(value, f"{path}[{i}]")

        messages = conv.messages()

        # 检查整个对话历史
        check_surrogates(messages, "messages")

        for piece in client.stream(
                messages,
                temperature=0.3,
                max_tokens=500
        ):
            print(piece, end="", flush=True)
        for piece in client.stream(conv.messages(), temperature = 0.3 , max_tokens = 500):
            print(piece , end="", flush= True)
        r = client.last
        conv.add_assistant(r.message)
        ttft = f"{r.ttft:.2f}s" if r.ttft is not None else "-"
        print(f"\n  [TTFT {ttft} | 总 {r.latency:.2f}s | 输入 {r.prompt_tokens}"
              f"（缓存 {r.cache_hit_tokens}）| 输出 {r.completion_tokens} | ¥{r.cost:.5f}]")
    print("\n本次会话：", client.ledger)


if __name__ == "__main__":
    main()