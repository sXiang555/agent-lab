from __future__ import annotations

import json
import re
from importlib.resources import files
from pathlib import Path

from .comparison import RunResult

RUN_ID = re.compile(r"(?<![a-z0-9])(?:DET|VIS)-[0-9]{3}(?![a-z0-9])", re.IGNORECASE)
DATA = files("experiment_pilot").joinpath("data")
BASELINE = re.compile(rf"(?:基线|baseline)\s*[:：=]?\s*({RUN_ID.pattern})", re.I)
CANDIDATE = re.compile(rf"(?:候选|candidate)\s*[:：=]?\s*({RUN_ID.pattern})", re.I)
RELATIVE = re.compile(
    rf"({RUN_ID.pattern})\s*(?:相比|相较于|相对于|比)\s*({RUN_ID.pattern})", re.I
)


def ordered_run_ids(question: str) -> list[str]:
    ids = [match.group().upper() for match in RUN_ID.finditer(question)]
    if len(ids) != 2:
        return ids
    baseline, candidate = BASELINE.search(question), CANDIDATE.search(question)
    if baseline and baseline[1].upper() in ids:
        old = baseline[1].upper()
        new = candidate[1].upper() if candidate else ids[1 - ids.index(old)]
        if old != new:
            return [old, new]
    relative = RELATIVE.search(question)
    if relative:
        return [relative[2].upper(), relative[1].upper()]
    return ids


class Catalog:
    def __init__(self, path: Path | None = None) -> None:
        source = path if path is not None else DATA.joinpath("runs.json")
        records = [RunResult.model_validate(item)
                   for item in json.loads(source.read_text(encoding="utf-8"))]
        self._runs = {}
        for record in records:
            if not RUN_ID.fullmatch(record.run_id) or record.run_id != record.run_id.upper():
                raise ValueError(f"Invalid run ID: {record.run_id}")
            if record.run_id in self._runs:
                raise ValueError(f"Duplicate run ID: {record.run_id}")
            self._runs[record.run_id] = record

    def list(self, project: str) -> list[RunResult]:
        return [record for record in self._runs.values() if record.project == project]

    def get(self, project: str, run_id: str) -> RunResult | None:
        record = self._runs.get(run_id.upper())
        return record if record is not None and record.project == project else None
