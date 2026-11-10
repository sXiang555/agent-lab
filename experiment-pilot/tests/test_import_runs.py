from __future__ import annotations

import hashlib
import json
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from experiment_pilot.api import create_app
from experiment_pilot.catalog import Catalog
from experiment_pilot.comparison import compare_runs
from experiment_pilot.config import Settings
from experiment_pilot.import_runs import load_manifest, read_solver_log


def _log_row(epoch, ap, ap_small):
    stats = [ap, 0.8, 0.6, ap_small, 0.5, 0.6, 0.1, 0.2, 0.3, 0.2, 0.3, 0.4]
    return json.dumps({"train_loss": 0.123, "test_coco_eval_bbox": stats, "epoch": epoch}) + "\n"


@pytest.fixture
def experiment_dir(tmp_path):
    files = {
        "train.json": '{"images":[{"id":1}],"annotations":[]}',
        "val.json": '{"images":[{"id":2}],"annotations":[]}',
        "training.json": '{"epochs":72,"batch_size":16}',
        "training-copy.json": '{ "batch_size": 16, "epochs": 72 }',
        "evaluation.json": '{"precision":"fp32","metric":"COCO bbox"}',
        "base.log": _log_row(70, 0.55, 0.34) + _log_row(71, 0.485, 0.312),
        "candidate.log": _log_row(70, 0.512, 0.33) + _log_row(71, 0.497, -1),
    }
    for name, data in files.items():
        (tmp_path / name).write_text(data, encoding="utf-8")
    return tmp_path


def _manifest(root, candidate_epoch=71):
    common = {
        "seed": 42, "train_manifest": "train.json", "validation_manifest": "val.json",
        "evaluation_controls": "evaluation.json",
    }
    base = {
        **common, "run_id": "DET-101", "label": "baseline", "revision": "aaa111",
        "log": "base.log", "epoch": 71, "training_controls": "training.json",
    }
    candidate = {
        **common, "run_id": "DET-102", "label": "candidate", "revision": "bbb222",
        "log": "candidate.log", "epoch": candidate_epoch, "training_controls": "training-copy.json",
    }
    path = root / "manifest.json"
    path.write_text(json.dumps({"version": 1, "runs": [base, candidate]}), encoding="utf-8")
    return path


def test_import_cli_preserves_fixed_epoch_and_log_evidence(experiment_dir):
    manifest = _manifest(experiment_dir)
    catalog_path = experiment_dir / "catalog.json"
    command = [sys.executable, "-m", "experiment_pilot.import_runs",
               str(manifest), "--output", str(catalog_path)]
    run = subprocess.run(command, cwd=experiment_dir.parent, capture_output=True, check=True)
    assert "Imported 2 runs" in run.stdout.decode()
    catalog = Catalog(catalog_path)
    baseline, candidate = catalog.list("detection")
    assert baseline.log_evidence.epoch == 71
    assert baseline.log_evidence.line == 2
    assert baseline.log_evidence.sha256 == hashlib.sha256(
        (experiment_dir / "base.log").read_bytes()
    ).hexdigest()
    assert baseline.ap_small == 0.312
    assert candidate.ap_small is None
    assert baseline.training_protocol == candidate.training_protocol
    assert compare_runs(baseline, candidate).delta_ap_points == 1.2

    before = catalog_path.read_bytes()
    retry = subprocess.run(command, cwd=experiment_dir.parent, capture_output=True)
    assert retry.returncode == 1
    assert catalog_path.read_bytes() == before
    assert list(experiment_dir.glob("tmp*")) == []


def test_imported_epoch_mismatch_appears_in_workflow_and_approval(experiment_dir):
    manifest = _manifest(experiment_dir, candidate_epoch=70)
    path = experiment_dir / "catalog.json"
    records = load_manifest(manifest)
    path.write_text(json.dumps([record.model_dump() for record in records]), encoding="utf-8")
    settings = Settings(state_dir=experiment_dir / "state", runs_file=path)
    with TestClient(create_app(settings)) as client:
        response = client.post("/reviews", headers={"Authorization": "Bearer demo-analyst"}, json={
            "request_id": "imported-runs", "question": "比较 DET-101 和 DET-102",
            "request_rerun": True,
        })
    event_frames = dict((a.removeprefix("event: "), json.loads(b.removeprefix("data: ")))
                        for a, b in (frame.splitlines() for frame in response.text.strip().split("\n\n")))
    review = event_frames["result"]
    assert review["result"]["status"] == "incomparable"
    assert review["result"]["reasons"] == ["metric_epoch"]
    assert review["result"]["delta_ap_points"] is None
    assert "base.log:2（epoch 71" in review["evidence"][0]["text"]
    assert "candidate.log:1（epoch 70" in review["evidence"][1]["text"]
    assert event_frames["approval"]["metric_epoch"] == 71


@pytest.mark.parametrize(("rows", "reason"), [
    (_log_row(71, 0.485, 0.312) * 2, "occurs more than once"),
    (_log_row(71, 48.5, 0.312), "must be a number in"),
    (_log_row(70, 0.485, 0.312), "epoch 71 not found"),
    (_log_row(71, 0.485, 0.312) + '{"epoch":', "expected a solver JSONL row"),
])
def test_import_rejects_ambiguous_or_malformed_scores(tmp_path, rows, reason):
    path = tmp_path / "bad.log"
    path.write_text(rows, encoding="utf-8")
    with pytest.raises(ValueError, match=reason):
        read_solver_log(path, 71)
