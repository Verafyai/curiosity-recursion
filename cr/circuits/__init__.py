"""Research circuits: topics (what a finished Studio output needs) and the steps that can fill them.

Stage numbers are kin's run-pass STAGE_LABELS (lib/search/run-pass.ts):
1 identity resolution, 2 vital records, 3 place and migration, 4 kin graph,
5 military service, 6 local holdings, 7 lineage assembly.

`template` names the report layout used by cr/writer.py (service-record, the-crossing,
book-of-daniel).

Each topic lists steps in the order to try them. Level 0 runs every step of every topic.
Coverage per topic is covered, leads_only or missing (cr/generators/rules.py checklist()).
Circuits and steps are data, in YAML beside this file.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel

from cr.models import StepSpec

STAGE_LABELS = [
    "",
    "identity resolution",
    "vital records",
    "place and migration",
    "kin graph",
    "military service",
    "local holdings",
    "lineage assembly",
]


class Topic(BaseModel):
    id: str
    label: str
    fields: list[str]
    keywords: list[str]
    steps: list[str]
    candidate_counts: bool = True  # do name-match leads count as "leads_only"?


class Circuit(BaseModel):
    id: str
    title: str
    template: str
    blurb: str
    opening: list[str]
    topics: list[Topic]


HERE = Path(__file__).resolve().parent

# Steps: every checklist step any circuit can use (steps.yaml). A step is `live` (a keyless public
# client) or `stub` (a source that needs a login, a key, a letter or a visit; `why_stub` says which).
STEPS: dict[str, StepSpec] = {d["id"]: StepSpec(**d) for d in yaml.safe_load((HERE / "steps.yaml").read_text())["steps"]}

# Circuits: one YAML file per heritage or kin group. Add a file to add a circuit.
CIRCUITS: dict[str, Circuit] = {}
for _f in sorted(HERE.glob("*.yaml")):
    if _f.name == "steps.yaml":
        continue
    _c = Circuit(**yaml.safe_load(_f.read_text()))
    missing = [s for t in _c.topics for s in t.steps if s not in STEPS]
    if missing:
        raise ValueError(f"{_f.name}: unknown steps {missing}")
    CIRCUITS[_c.id] = _c


def circuit_for(circuit_id: str) -> Circuit:
    return CIRCUITS[circuit_id]
