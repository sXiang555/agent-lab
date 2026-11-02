
from chatbot.config import load_settings
from chatbot.llm import LLMClient
from openai import OpenAI, OpenAIError


def main():
    client = LLMClient(load_settings(".env"))
    user_input = input("user:")
    user_message = [{"role": "user", "content": user_input}]
    try:
        resp = client.chat(user_message)

        content = resp.choices[0].message.content
        if content:
            print("assistant:",content)
        else:
            print("模型没有返回文本内容")
    except OpenAIError as e:
        print(f"模型请求失败:{e}")


if __name__ == "__main__":
    main()