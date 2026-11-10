from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from psycopg.conninfo import conninfo_to_dict

from experiment_pilot.api import create_app
from experiment_pilot.config import Settings
from experiment_pilot.model import ModelGateway

ANALYST_TOKEN = "test-analyst-" + "a" * 32
REVIEWER_TOKEN = "test-reviewer-" + "b" * 32


def test_public_showcase_is_separate_from_custom_runs_and_has_no_side_effects(tmp_path, monkeypatch):
    records = tmp_path / "catalog.json"
    records.write_text(json.dumps([{
        "run_id": "DET-001", "project": "detection", "label": "custom-run-sentinel",
        "revision": "private-revision", "split_fingerprint": "split", "training_protocol": "train",
        "evaluation_protocol": "eval", "seed": 9, "ap": 0.8,
    }]))

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("Showcase must not invoke any model")

    monkeypatch.setattr(ModelGateway, "ask", fail_if_called)
    settings = Settings(state_dir=tmp_path / "state", demo_auth=False, public_showcase=True,
                        analyst_token=ANALYST_TOKEN, reviewer_token=REVIEWER_TOKEN,
                        runs_file=records)
    with TestClient(create_app(settings)) as client:
        assert client.get("/ready").json() == {"status": "ready"}
        public = client.get("/showcase/improvement").json()
        assert public["result"]["delta_ap_points"] == 1.2
        assert "custom-run-sentinel" not in json.dumps(public)
        assert client.get("/runs", headers={"Authorization": "Bearer demo-analyst"}).status_code == 401
        assert client.get("/runs", headers={"Authorization": f"Bearer {ANALYST_TOKEN}"}).json()[0][
            "label"
        ] == "custom-run-sentinel"
        store = client.app.state.service.store
        assert store.pending("detection") == [] and store.queued_count() == 0


def test_production_configuration_rejects_demo_or_missing_postgres():
    with pytest.raises(ValueError, match="Production requires PostgreSQL"):
        Settings(production=True, database_url="postgresql://pilot@db/pilot")
    with pytest.raises(ValueError, match="Production requires PostgreSQL"):
        Settings(production=True, demo_auth=False, analyst_token=ANALYST_TOKEN,
                 reviewer_token=REVIEWER_TOKEN)


def test_file_secrets_are_loaded_and_conflicting_inputs_fail(tmp_path, monkeypatch):
    analyst = tmp_path / "analyst"
    analyst.write_text(ANALYST_TOKEN + "\n")
    db = tmp_path / "db"
    db.write_text("synthetic-pass with spaces\n")
    monkeypatch.setenv("PILOT_DEMO_AUTH", "0")
    monkeypatch.setenv("PILOT_PRODUCTION", "1")
    monkeypatch.setenv("PILOT_ANALYST_TOKEN_FILE", str(analyst))
    monkeypatch.setenv("PILOT_REVIEWER_TOKEN", REVIEWER_TOKEN)
    monkeypatch.setenv("PILOT_DATABASE_URL", "postgresql://pilot@db:5432/pilot")
    monkeypatch.setenv("PILOT_DB_PASSWORD_FILE", str(db))
    settings = Settings.from_env()
    assert settings.analyst_token == ANALYST_TOKEN
    assert conninfo_to_dict(settings.database_url)["password"] == "synthetic-pass with spaces"
    assert create_app(settings).openapi_url is None
    monkeypatch.setenv("PILOT_ANALYST_TOKEN", ANALYST_TOKEN)
    with pytest.raises(ValueError, match="Set only one"):
        Settings.from_env()
