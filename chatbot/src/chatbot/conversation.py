import json
from typing import Any
from pathlib import Path



class Conversation:

    def __init__(self, system_prompt: str, max_turns: int = 6):
        # 初始化系统提示词
        self.system_prompt = system_prompt

        # 初始化最大对话轮数
        if max_turns < 1:
            raise ValueError("max_turns 必须大于等于 1")

        self.max_turns = max_turns

        # 保存每一轮对话
        self.messages_turns: list[list[dict[str, str]]] = []

    def add_user(self, content: str):
        message = {
            "role": "user",
            "content": content
        }

        new_list = [message]
        self.messages_turns.append(new_list)

        # 只保留最近 max_turns 轮
        self.messages_turns = self.messages_turns[-self.max_turns:]

    def add_assistant(self, content: str):
        if not self.messages_turns:
            raise RuntimeError("请先添加用户消息")

        if self.messages_turns[-1][-1]["role"] != "user":
            raise RuntimeError("当前轮次已经添加过 Assistant 消息")

        message = {
            "role": "assistant",
            "content": content
        }

        self.messages_turns[-1].append(message)

    def get_messages(self) -> list[dict]:
        history = [
            message
            for turn in self.messages_turns
            for message in turn
        ]

        return [
            {"role": "system", "content": self.system_prompt},
            *history
        ]

    def clear(self) ->None:
        self.messages_turns.clear()


    def save(self, file_path: str | Path) ->None:
        data ={
            "version": 1,
            "system_prompt": self.system_prompt,
            "max_turns": self.max_turns,
            "messages_turns": self.messages_turns
        }

        path = Path(file_path)
        path.parent.mkdir(parents=True,exist_ok=True)

        with path.open("w",encoding="utf-8") as f:
            json.dump(data,f,ensure_ascii=False,indent=4)


    @classmethod
    def load(cls, file_path: str | Path) ->"Conversation":
        path = Path(file_path)
        with path.open("r",encoding="utf-8") as f:
            data:dict[str,Any] = json.load(f)
            conversation = Conversation(
                system_prompt=data["system_prompt"],
                max_turns=data.get("max_turns")
            )
            conversation.messages_turns = data["messages_turns"]
            return conversation