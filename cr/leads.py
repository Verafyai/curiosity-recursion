"""Lead tree with a value score and UCT-style best-first selection (spec section 6). Pure, deterministic.

LATS (`zhou2024lats`), Tree of Thoughts (`yao2023tot`) and RAP (`hao2023rap`) search a tree of
reasoning steps with a value estimate; UCT (`kocsis2006uct`) and UCB1 (`auer2002ucb`) balance a
branch's observed reward against how rarely it was tried. CR uses the cheap version, MCTS-lite: no
simulated rollouts (they would cost tool calls); a real call's reward is backed up to the ancestors.
"""
from __future__ import annotations

import math
from typing import Optional

from pydantic import BaseModel, Field

from cr.ledger import NOVELTY_BY_KEY, Decision, QuerySpec

# Preregistered start weights (w_n, w_y, w_r, w_g, w_c), frozen in bench/PREREGISTRATION-v0.2.md.
WEIGHTS = (0.3, 0.3, 0.15, 0.25, 0.1)
UCT_C = 0.7
VALUE_FLOOR = 0.05
LIVE_TOOLS = ("ia_fts", "ia_fulltext", "ia_inside", "ia_inside_pages", "ia_title", "chronam", "wikidata_search", "wikidata_entities")
# Era-table priors for expected yield by viewpoint (before any call of the run). Set from the v0.1.0
# design notes, not from benchmark results.
YIELD_PRIOR = {"military": 0.4, "census": 0.35, "church": 0.3, "newspaper": 0.3, "land": 0.35, "probate": 0.2, "immigration": 0.15,
               "reference": 0.25}


class Lead(BaseModel):
    id: str
    lane: str
    spec: QuerySpec
    parent: Optional[str] = None
    depth: int = 0
    question: str = ""
    grounding: str = ""
    components: dict[str, float] = Field(default_factory=dict)
    value: float = 0.0
    n: int = 0
    reward_sum: float = 0.0
    status: str = "open"  # open | done | blocked | dropped


def novelty_of(decision: Decision | None) -> float:
    if decision is None or decision.decision == "new":
        return 1.0
    if decision.decision == "revisit":
        return NOVELTY_BY_KEY.get(decision.key_type or "", 0.3)
    if decision.decision == "unchecked":
        return 1.0
    return 0.0


def value_score(spec: QuerySpec, decision: Decision | None, expected_yield: float, gap_state: str, cost: float = 1.0,
                weights=WEIGHTS) -> tuple[float, dict[str, float]]:
    wn, wy, wr, wg, wc = weights
    comp = {"novelty": novelty_of(decision), "expected_yield": max(0.0, min(1.0, expected_yield)),
            "reachability": 1.0 if spec.tool in LIVE_TOOLS else (0.5 if spec.tool == "stub" else 0.0),
            "gap_fill": {"missing": 1.0, "leads_only": 0.5, "covered": 0.0}.get(gap_state, 0.5), "cost": cost}
    v = wn * comp["novelty"] + wy * comp["expected_yield"] + wr * comp["reachability"] + wg * comp["gap_fill"] - wc * comp["cost"]
    return max(0.0, min(1.0, v)), comp


class LeadTree(BaseModel):
    nodes: dict[str, Lead] = Field(default_factory=dict)
    lane_seq: dict[str, int] = Field(default_factory=dict)

    def add(self, lane: str, spec: QuerySpec, parent: Optional[str], value: float, components: dict[str, float], question: str = "",
            grounding: str = "") -> Lead:
        self.lane_seq[lane] = self.lane_seq.get(lane, 0) + 1
        depth = (self.nodes[parent].depth + 1) if parent and parent in self.nodes else 0
        ld = Lead(id=f"{lane}.{self.lane_seq[lane]}", lane=lane, spec=spec, parent=parent, depth=depth, value=value, components=components,
                  question=question or spec.purpose, grounding=grounding or spec.grounding)
        self.nodes[ld.id] = ld
        return ld

    def frontier(self, lane: Optional[str] = None) -> list[Lead]:
        return [x for x in self.nodes.values() if x.status == "open" and (lane is None or x.lane == lane)]

    def uct(self, ld: Lead) -> float:
        mean = (ld.reward_sum / ld.n) if ld.n else ld.value
        np = (self.nodes[ld.parent].n if ld.parent and ld.parent in self.nodes else sum(1 for x in self.nodes.values() if x.n)) + 1
        return mean + UCT_C * math.sqrt(math.log(np + 1) / (1 + ld.n))

    def select(self, lane: Optional[str] = None, floor: float = VALUE_FLOOR) -> Optional[Lead]:
        cands = [x for x in self.frontier(lane) if x.value >= floor]
        if not cands:
            return None
        return max(cands, key=lambda x: (round(self.uct(x), 9), round(x.value, 9), -self.seq_of(x)))

    @staticmethod
    def seq_of(ld: Lead) -> int:
        return int(ld.id.rsplit(".", 1)[1])

    def merge(self, other: "LeadTree", lane: str) -> None:
        """Take back one lane's nodes from a lane worker (lanes are disjoint, so this never conflicts)."""
        for k, v in other.nodes.items():
            if v.lane == lane:
                self.nodes[k] = v
        self.lane_seq[lane] = max(self.lane_seq.get(lane, 0), other.lane_seq.get(lane, 0))

    def subtree(self, lane: str) -> "LeadTree":
        return LeadTree(nodes={k: v for k, v in self.nodes.items() if v.lane == lane}, lane_seq={lane: self.lane_seq.get(lane, 0)})

    def backup(self, lead_id: str, reward: float) -> None:
        cur = lead_id
        while cur and cur in self.nodes:
            nd = self.nodes[cur]
            nd.n += 1
            nd.reward_sum += reward
            cur = nd.parent
