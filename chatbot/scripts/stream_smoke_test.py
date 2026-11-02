
from chatbot.config import load_settings
from chatbot.llm import LLMClient
from openai import OpenAI, OpenAIError


def main():
    client = LLMClient(load_settings(".env"))
    user_input = input("user:")
    user_message = [{"role": "user", "content": user_input}]
    try:
        print("assistant:",end="",flush=True)
        for piece in client.stream(user_message):
            print(piece,end="",flush=True)
    except OpenAIError as e:
        print(f"模型请求失败:{e}")


if __name__ == "__main__":
    main()