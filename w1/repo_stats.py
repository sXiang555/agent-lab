import asyncio
import time

import httpx
from httpx import HTTPError
from pydantic import BaseModel,Field,ValidationError



REPOS = [
    "astral-sh/uv",
    "pydantic/pydantic",
    "encode/httpx",
    "openai/openai-python",
    "this-owner/does-not-exist-404",   # 故意放一个不存在的，练习错误处理
]


class RepoInfo(BaseModel):
    full_name: str
    stars: int = Field(alias="stargazers_count",ge=0)
    language : str | None = None
    open_issues: int = Field(alias="open_issues_count", ge=0)

async def fetch_repo(repo: str , client: httpx.AsyncClient) -> RepoInfo | BaseException:
    r = await client.get(f"https://api.github.com/repos/{repo}")
    r.raise_for_status()
    return RepoInfo.model_validate(r.json())

async def fetch_all(repos: list[str]) -> list[RepoInfo | BaseException]:
    async with httpx.AsyncClient(timeout=15 , headers={"User-Agent" : "agent-lab"}) as client :
        return await asyncio.gather(*(fetch_repo(r,client) for r in REPOS) , return_exceptions= True)


def summarize(results: list[RepoInfo | BaseException], repos: list[str]) -> tuple[list[RepoInfo],list[str]]:
    ok : list[RepoInfo] = []
    false : list[str] = []
    for res , repo in zip(results,repos) :
        if isinstance(res , RepoInfo):
            ok.append(res)
        elif isinstance(res , httpx.HTTPStatusError):
            false.append(f"{repo}: HTTP {res.response.status_code}")
        elif isinstance(res , ValidationError):
            false.append(f"{res}: 返回数据不合法 {res.error_count()} 处")
        else:
            false.append(f"{repo}: {type(res).__name__} {res}")
    return ok,false

def main():
    start = time.perf_counter()
    results = asyncio.run(fetch_all(REPOS))
    ok , false = summarize(results , REPOS)
    for info in sorted(ok, key=lambda x: x.stars, reverse=True):
        print(f"{info.full_name:<28} ⭐ {info.stars:>7}  {info.language or '-'}")
    for f in false:
        print("失败:", f)
    print(f"耗时 {time.perf_counter() - start:.2f}s")


if __name__ == '__main__':
    main()