from __future__ import annotations

import os
from dataclasses import asdict
from hmac import compare_digest

from mcp.server.fastmcp import FastMCP
from pydantic import Field
from typing_extensions import Annotated

from .catalog import Catalog
from .comparison import compare_runs
from .config import Settings
from .retrieval import Retriever


def create_server(settings: Settings, token: str) -> FastMCP:
    roles = [(settings.analyst_token, "detection"), (settings.reviewer_token, "detection")]
    if settings.demo_auth:
        roles.append((settings.other_token, "vision-private"))
    project = next((project for key, project in roles
                    if compare_digest(key.encode(), token.encode())), None)
    if project is None:
        raise ValueError("Set PILOT_MCP_TOKEN to a valid role token")
    catalog = Catalog(settings.runs_file)
    retriever = Retriever(settings) if project == "detection" else None
    server = FastMCP("ExperimentPilot", instructions="查询本项目的实验记录、AP 对比和手册。")

    @server.tool()
    def list_runs() -> list[dict]:
        """列出当前身份可访问的实验运行。"""
        return [record.model_dump(mode="json") for record in catalog.list(project)]

    @server.tool()
    def get_run(run_id: str) -> dict:
        """读取一条实验记录，包括数据划分、seed 和 AP。"""
        record = catalog.get(project, run_id)
        return record.model_dump(mode="json") if record else {"error": "运行不可用"}

    @server.tool()
    def compare_experiments(baseline: str, candidate: str) -> dict:
        """核对两条实验能否公平比较，返回有证据支持的 AP 点差值。"""
        left, right = catalog.get(project, baseline), catalog.get(project, candidate)
        if left is None or right is None:
            return {"status": "insufficient_evidence", "reasons": ["run_unavailable"]}
        return {**asdict(compare_runs(left, right)),
                "sources": [f"run:{left.run_id}", f"run:{right.run_id}"]}

    @server.tool()
    def search_handbook(query: Annotated[str, Field(min_length=1, max_length=2000)]) -> list[dict]:
        """混合检索实验手册，返回带稳定引用编号的条目。"""
        return retriever.search(query) if retriever else []

    return server


def main() -> None:
    settings = Settings.from_env()
    token = os.getenv("PILOT_MCP_TOKEN", settings.analyst_token if settings.demo_auth else "")
    create_server(settings, token).run(transport="stdio")


if __name__ == "__main__":
    main()
