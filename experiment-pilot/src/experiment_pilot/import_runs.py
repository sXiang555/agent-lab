"""Convert RT-DETR solver JSONL metrics into an ExperimentPilot catalog."""

from __future__ import annotations

import argparse
import hashlib
import json
from functools import cache
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from .catalog import RUN_ID
from .comparison import LogEvidence, RunResult

Nonempty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Epoch = Annotated[int, Field(ge=0, strict=True)]


class ImportEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: Nonempty
    project: Literal["detection", "vision-private"] = "detection"
    label: Nonempty
    revision: Nonempty
    seed: Epoch
    epoch: Epoch
    log: Path
    train_manifest: Path
    validation_manifest: Path
    training_controls: Path
    evaluation_controls: Path


class ImportManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    runs: list[ImportEntry] = Field(min_length=1)


def _metric(value: object, name: str, location: str) -> float | None:
    if type(value) not in (int, float) or (value != -1 and not 0 <= value <= 1):
        raise ValueError(f"{location}: {name} must be a number in [0, 1] or -1")
    return None if value == -1 else float(value)


def read_solver_log(path: Path, epoch: int) -> tuple[float | None, float | None, LogEvidence]:
    digest = hashlib.sha256()
    selected = None
    with path.open("rb") as log:
        for number, line in enumerate(log, start=1):
            digest.update(line)
            if not line.strip():
                continue
            location = f"{path}:{number}"
            try:
                row = json.loads(line)
            except (UnicodeError, ValueError) as exc:
                raise ValueError(f"{location}: expected a solver JSONL row") from exc
            if not isinstance(row, dict) or type(row.get("epoch")) is not int or row["epoch"] < 0:
                raise ValueError(f"{location}: invalid or missing epoch")
            if row["epoch"] != epoch:
                continue
            if selected is not None:
                raise ValueError(f"{location}: epoch {epoch} occurs more than once")
            stats = row.get("test_coco_eval_bbox")
            if not isinstance(stats, list) or len(stats) != 12:
                raise ValueError(f"{location}: expected 12 COCO bbox metrics")
            selected = (
                _metric(stats[0], "AP", location),
                _metric(stats[3], "AP_small", location),
                number,
            )
    if selected is None:
        raise ValueError(f"{path}: epoch {epoch} not found")
    ap, ap_small, line_number = selected
    return ap, ap_small, LogEvidence(
        filename=path.name, sha256=digest.hexdigest(), epoch=epoch, line=line_number,
    )


def load_manifest(path: Path) -> list[RunResult]:
    manifest = ImportManifest.model_validate_json(path.read_bytes())
    root = path.resolve().parent

    @cache
    def file_digest(file: Path) -> str:
        with file.open("rb") as source:
            return hashlib.file_digest(source, "sha256").hexdigest()

    @cache
    def controls_digest(file: Path) -> str:
        value = json.loads(file.read_bytes())
        if not isinstance(value, dict) or not value:
            raise ValueError(f"{file}: controls must be a nonempty JSON object")
        canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(canonical.encode()).hexdigest()

    records = []
    seen = set()
    for entry in manifest.runs:
        if not RUN_ID.fullmatch(entry.run_id) or entry.run_id != entry.run_id.upper():
            raise ValueError(f"Invalid run ID: {entry.run_id}")
        if entry.run_id in seen:
            raise ValueError(f"Duplicate run ID: {entry.run_id}")
        seen.add(entry.run_id)

        log = (root / entry.log).resolve()
        ap, ap_small, source = read_solver_log(log, entry.epoch)
        train = file_digest((root / entry.train_manifest).resolve())
        validation = file_digest((root / entry.validation_manifest).resolve())
        split = hashlib.sha256(f"train:{train}\nvalidation:{validation}".encode()).hexdigest()
        training = controls_digest((root / entry.training_controls).resolve())
        evaluation = controls_digest((root / entry.evaluation_controls).resolve())
        records.append(RunResult(
            run_id=entry.run_id, project=entry.project, label=entry.label, revision=entry.revision,
            split_fingerprint=f"sha256:{split}", training_protocol=f"sha256:{training}",
            evaluation_protocol=f"sha256:{evaluation}", seed=entry.seed,
            ap=ap, ap_small=ap_small, log_evidence=source,
        ))
    return records


def write_catalog(path: Path, records: list[RunResult]) -> None:
    """Publish a complete catalog atomically, refusing to overwrite inputs or older catalogs."""
    payload = json.dumps([row.model_dump(mode="json") for row in records],
                         ensure_ascii=False, indent=2) + "\n"
    with NamedTemporaryFile(mode="w", dir=path.parent, encoding="utf-8") as temp:
        temp.write(payload)
        temp.flush()
        path.hardlink_to(temp.name)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        records = load_manifest(args.manifest)
        write_catalog(args.output, records)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Import failed: {exc}\n")
    print(f"Imported {len(records)} runs into {args.output}")


if __name__ == "__main__":
    main()
