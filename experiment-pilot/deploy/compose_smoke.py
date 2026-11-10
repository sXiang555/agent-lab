"""Run after docker compose up --build --wait against an isolated demo deployment."""

import json
import os
from uuid import uuid4

import httpx

BASE = os.getenv("PILOT_SMOKE_BASE", "http://127.0.0.1:3000/api/pilot")
ANALYST = {"Authorization": "Bearer demo-analyst"}
REVIEWER = {"Authorization": "Bearer demo-reviewer"}


def sse(response: httpx.Response) -> dict:
    response.raise_for_status()
    result = {}
    for frame in response.text.strip().split("\n\n"):
        event, data = frame.splitlines()
        result[event.removeprefix("event: ")] = json.loads(data.removeprefix("data: "))
    if "error" in result:
        raise RuntimeError(result["error"])
    return result


with httpx.Client(base_url=BASE, timeout=30) as client:
    health = client.get("health").raise_for_status().json()
    assert health["retrieval"] == "pgvector", health
    started = sse(client.post("reviews", headers=ANALYST, json={
        "request_id": uuid4().hex,
        "question": "对比 DET-001 和 DET-003，然后申请按基线口径复跑。",
        "request_rerun": True,
    }))
    assert started["result"]["result"]["status"] == "incomparable"
    assert started["result"]["status"] == "pending_approval"
    assert any(row["source_id"].startswith("kb:") for row in started["result"]["evidence"])
    review_id = started["review"]["review_id"]
    path = f"reviews/{review_id}/approval"
    body = {"proposal_id": started["approval"]["proposal_id"], "approve": True, "reason": "compose smoke"}
    first = sse(client.post(path, headers=REVIEWER, json=body))["result"]
    second = sse(client.post(path, headers=REVIEWER, json=body))["result"]
    assert first["proposal"]["state"] == "approved"
    assert first["proposal"]["job_id"] == second["proposal"]["job_id"]
    print("Postgres/pgvector + SSE + approval smoke passed")
