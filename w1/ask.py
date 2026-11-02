import json
import argparse
import os
import sys

import openai
from dotenv import load_dotenv
from openai import OpenAI, api_key


def parse_price(raw: str) -> tuple[float, float, float]:
    hit, miss, out = (float(x) for x in raw.split(","))
    return hit, miss, out

def cost_yuan(usage , price :tuple[float,float,float]) ->float:
    hit_price , miss_price , out_price = price
    hit = getattr(usage , "prompt_cache_hit_tokens", None) or 0
    miss = getattr(usage , "prompt_cache_miss_tokens" , None)
    if miss is None:
        miss = usage.prompt_tokens - hit
    return (hit * hit_price + miss * miss_price + usage.completion_tokens * out_price) / 1_000_000

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("question")
    parser.add_argument("--env" , default=".env")
    parser.add_argument("--max-tokens", type=int , default=500)
    args = parser.parse_args()

    load_dotenv(args.env,override=True)
    client = OpenAI(
        base_url= os.environ["LLM_BASE_URL"],
        api_key= os.environ["LLM_API_KEY"],
        max_retries=3,
        timeout = 60.0,
    )
    extra_body = json.loads(os.environ.get("LLM_EXTRA_BODY", "{}"))
    price = parse_price(os.environ.get("LLM_PRICE", "0,0,0"))

    try:
        resp = client.chat.completions.create(
            model=os.environ["LLM_MODEL"],
            messages=[
                {"role": "system", "content": "你是一个简洁的技术助手，用中文回答。"
                                              "你是一个简洁的技术助手，用中文回答。"
                                              "你是一个简洁的技术助手，用中文回答。"
                                              "你是一个简洁的技术助手，用中文回答。"
                                              "你是一个简洁的技术助手，用中文回答。"
                                              "你是一个简洁的技术助手，用中文回答。"
                                              "你是一个简洁的技术助手，用中文回答。"
                                              ""},
                {"role": "user", "content": args.question},
            ],
            max_tokens=args.max_tokens,
            temperature=0.3,
            extra_body=extra_body
        )
    except openai.AuthenticationError:
        print("401：API key 不对。检查", args.env, "里的 LLM_API_KEY。", file=sys.stderr)
        return 1
    except openai.RateLimitError as e:
        print("429：请求太快或额度用完（已自动重试 3 次）。", e.message, file=sys.stderr)
        return 1
    except openai.BadRequestError as e:
        print("400：请求参数有问题，通常是模型名或扩展参数不对：", e.message, file=sys.stderr)
        return 1
    except openai.APIConnectionError:
        print("连不上服务器：检查网络、代理和 LLM_BASE_URL。", file=sys.stderr)
        return 1
    except openai.APIStatusError as e:
        print(f"HTTP {e.status_code}：{e.message}", file=sys.stderr)
        return 1
    choice = resp.choices[0]
    print(choice.message.content)
    print('-'*40)
    print("模型：",resp.model,"| finish_reason:", choice.finish_reason)
    if choice.finish_reason== "length":
        print("回答被max_tokens 截断了，调大 --max-tokens 再试")
    u = resp.usage
    assert u is not None
    print(f"tokens: 输入 {u.prompt_tokens} / 输出 {u.completion_tokens} , 花费约 {cost_yuan(u,price):.5f}")
    return 0

if __name__ == '__main__':
    sys.exit(main())
