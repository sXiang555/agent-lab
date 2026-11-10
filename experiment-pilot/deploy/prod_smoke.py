"""Exercise the HTTPS deployment with isolated credentials and a persistent pending review."""

from __future__ import annotations

import argparse
import json
import ssl
from pathlib import Path
from time import monotonic, sleep
from uuid import uuid4

import httpx


def events(response: httpx.Response) -> dict:
    response.raise_for_status()
    frames = {}
    for frame in response.text.strip().split("\n\n"):
        event, data = frame.splitlines()
        frames[event.removeprefix("event: ")] = json.loads(data.removeprefix("data: "))
    assert "error" not in frames, frames.get("error")
    return frames


def wait_until_ready(client: httpx.Client) -> None:
    until = monotonic() + 70
    while monotonic() < until:
        try:
            response = client.get("/api/pilot/ready")
            if response.is_success and response.json().get("status") == "ready":
                return
        except (httpx.HTTPError, ValueError):
            pass
        sleep(2)
    raise RuntimeError("Deployment did not become ready")


def prepare(client: httpx.Client, analyst: dict, reviewer: dict) -> dict:
    home = client.get("/").raise_for_status()
    assert "frame-ancestors 'none'" in home.headers["content-security-policy"]
    assert home.headers["strict-transport-security"].startswith("max-age=")
    assert home.headers["x-content-type-options"] == "nosniff"
    health = client.get("/api/pilot/health").raise_for_status().json()
    assert health["retrieval"] == "pgvector" and not health["demo_auth"], health
    showcase = client.get("/api/pilot/showcase/improvement").raise_for_status().json()
    assert showcase["result"]["delta_ap_points"] == 1.2
    assert client.get("/api/pilot/openapi.json").status_code == 404
    assert client.get("/api/pilot/runs").status_code == 401
    assert client.get("/api/pilot/runs", headers={"Authorization": "Bearer demo-analyst"}).status_code == 401
    assert client.get("/api/pilot/approvals", headers=analyst).status_code == 403
    assert client.get("/api/pilot/approvals", headers=reviewer).json() == []
    assert client.post("/api/pilot/reviews", content=b"x" * 20_000, headers=analyst).status_code == 413
    started = events(client.post("/api/pilot/reviews", headers=analyst, json={
        "request_id": uuid4().hex,
        "question": "比较 DET-001 和 DET-003，然后申请补跑。",
        "request_rerun": True,
    }))
    assert started["result"]["status"] == "pending_approval"
    assert started["result"]["result"]["status"] == "incomparable"
    assert any(source["source_id"].startswith("kb:") for source in started["result"]["evidence"])
    review_id = started["review"]["review_id"]
    proposal_id = started["approval"]["proposal_id"]
    return {"review_id": review_id, "proposal_id": proposal_id}


def resume(client: httpx.Client, ids: dict, analyst: dict, reviewer: dict) -> None:
    review_id, proposal_id = ids["review_id"], ids["proposal_id"]
    body = {"proposal_id": proposal_id, "approve": True, "reason": "TLS production smoke"}
    review_path = f"/api/pilot/reviews/{review_id}"
    assert client.get(review_path, headers=analyst).json()["status"] == "pending_approval"
    assert client.post(review_path + "/approval", headers=analyst, json=body).status_code == 403
    approved = events(client.post(review_path + "/approval", headers=reviewer, json=body))
    retry = events(client.post(review_path + "/approval", headers=reviewer, json=body))
    first = approved["result"]["proposal"]
    assert first["state"] == "approved" and first["job_id"]
    assert retry["result"]["proposal"] == first
    assert client.get("/api/pilot/approvals", headers=reviewer).json() == []


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "resume"))
    parser.add_argument("--url", required=True)
    parser.add_argument("--ca", type=Path, required=True)
    parser.add_argument("--secrets-dir", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    args = parser.parse_args()
    analyst = {"Authorization": f"Bearer {(args.secrets_dir / 'analyst_token').read_text().strip()}"}
    reviewer = {"Authorization": f"Bearer {(args.secrets_dir / 'reviewer_token').read_text().strip()}"}
    context = ssl.create_default_context(cafile=str(args.ca))
    with httpx.Client(base_url=args.url, verify=context, timeout=12, trust_env=False) as client:
        wait_until_ready(client)
        if args.phase == "prepare":
            args.state.write_text(json.dumps(prepare(client, analyst, reviewer)))
        else:
            resume(client, json.loads(args.state.read_text()), analyst, reviewer)
    print(f"Production smoke {args.phase} passed")


if __name__ == "__main__":
    main()
