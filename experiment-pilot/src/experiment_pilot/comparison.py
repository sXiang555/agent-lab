from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LogEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    filename: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    epoch: int = Field(ge=0, strict=True)
    line: int = Field(ge=1, strict=True)


class RunResult(BaseModel):
    model_config = ConfigDict(frozen=True, allow_inf_nan=False)

    run_id: str
    project: str
    label: str
    revision: str
    split_fingerprint: str | None
    training_protocol: str | None
    evaluation_protocol: str | None
    seed: int | None
    ap: float | None
    ap_small: float | None = None
    log_evidence: LogEvidence | None = None


@dataclass(frozen=True)
class Comparison:
    status: Literal["comparable", "incomparable", "insufficient_evidence"]
    reasons: tuple[str, ...] = ()
    delta_ap_points: float | None = None


def compare_runs(baseline: RunResult, candidate: RunResult) -> Comparison:
    if baseline.run_id == candidate.run_id:
        return Comparison("incomparable", ("same_run",))

    controls = {
        "project": (baseline.project, candidate.project),
        "split_fingerprint": (baseline.split_fingerprint, candidate.split_fingerprint),
        "training_protocol": (baseline.training_protocol, candidate.training_protocol),
        "evaluation_protocol": (baseline.evaluation_protocol, candidate.evaluation_protocol),
        "seed": (baseline.seed, candidate.seed),
    }
    if baseline.log_evidence or candidate.log_evidence:
        controls["metric_epoch"] = (
            baseline.log_evidence.epoch if baseline.log_evidence else None,
            candidate.log_evidence.epoch if candidate.log_evidence else None,
        )
    missing = tuple(
        key for key, pair in controls.items() if any(value is None or value == "" for value in pair)
    )
    mismatches = tuple(
        key for key, (old, new) in controls.items() if key not in missing and old != new
    )
    if mismatches:
        return Comparison("incomparable", mismatches)

    old_ap, new_ap = baseline.ap, candidate.ap
    if old_ap is None or new_ap is None:
        return Comparison("insufficient_evidence", (*missing, "missing_ap"))
    if not (0.0 <= old_ap <= 1.0 and 0.0 <= new_ap <= 1.0):
        return Comparison("insufficient_evidence", (*missing, "invalid_ap"))
    if missing:
        return Comparison("insufficient_evidence", missing)

    return Comparison("comparable", delta_ap_points=round((new_ap - old_ap) * 100, 4))
