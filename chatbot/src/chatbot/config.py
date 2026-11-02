import json

from dotenv import load_dotenv
import os
from pathlib import Path

from openai import api_key, base_url
from pydantic import BaseModel, SecretStr
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]

class Settings(BaseModel):
    #大模型配置
    llm_api_key: SecretStr
    llm_base_url: str
    llm_model: str
    llm_extra_body: dict[str,Any] | None =None
    llm_price: tuple[float,float,float] = (0.0,0.0,0.0)


def load_settings(env_file: str = ".env.deepseek") ->Settings:
    env_path = PROJECT_ROOT/env_file
    load_dotenv(env_path,override=True)

    llm_api_key = os.getenv("LLM_API_KEY")
    llm_base_url = os.getenv("LLM_BASE_URL")
    llm_model = os.getenv("LLM_MODEL")

    extra_body_raw = os.getenv("LLM_EXTRA_BODY")
    llm_extra_body = json.loads(extra_body_raw) if extra_body_raw else None
    # 4. 解析价格配置
    price_raw = os.getenv("LLM_PRICE", "0,0,0")
    price_list = [float(x.strip()) for x in price_raw.split(",")]
    price = (price_list[0], price_list[1], price_list[2])

    # 5. 创建配置对象，交给 Pydantic 验证
    return Settings(
        llm_api_key=llm_api_key,
        llm_base_url=llm_base_url,
        llm_model=llm_model,
        llm_extra_body=llm_extra_body,
        llm_price=price
    )


