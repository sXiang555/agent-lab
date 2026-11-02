from pathlib import Path
from pyexpat.errors import messages

from chatbot.conversation import Conversation
from chatbot.llm import LLMClient
from chatbot.config import Settings, load_settings
import readline


def stream():
    client = LLMClient(settings= load_settings(".env"))
    conversation = Conversation(
        "你是一个助手"
    )
    while True:
        user_input = input("user：").strip()
        command, _, argument = user_input.partition(" ")
        argument = argument.strip()
        if not user_input:
            continue

        if user_input== "/quit" :
            break
        elif user_input=="/clear" :
            conversation.clear()
            continue
        elif user_input== "/help":
            show_help()
            continue
        elif user_input== "/cost":
            print(client.ledger)
            continue
        elif command=="/save":
            if not argument:
                print("正确用法：/save 文件名")
                continue
            conversation.save(get_session_path(argument))
            continue
        elif command=="/load":
            if not argument:
                print("正确用法: /load 文件名")
                continue
            path = get_session_path(argument)
            try:
                conversation = Conversation.load(path)
                print(f"会话已加载：{path}")
            except FileNotFoundError:
                print("找不到该会话文件")
            continue
        elif user_input.startswith("/"):
            print("未知命令，请输入'/help'查看命令")
            continue
        conversation.add_user(user_input)
        messages = conversation.get_messages()
        print("assistant:",end="",flush=True)
        for piece in client.stream(messages):
            if not piece:
                continue
            print(piece,end="",flush=True)
        print()
        result = client.last_result
        if result is  None:
            print("本次请求没有生成完整结果")
            continue
        conversation.add_assistant(result.content)





def show_help():
    print("""
========== Chatbot 帮助 ==========

/help       查看帮助
/clear      清空对话历史
/quit       退出程序

==================================
""")


SESSION_DIR = Path("sessions")
def get_session_path(filename: str) -> Path:
    filename = Path(filename).name

    if not filename.endswith(".json"):
        filename += ".json"

    return SESSION_DIR / filename

if __name__ == '__main__':
    stream()
