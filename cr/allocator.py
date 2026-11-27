"""UCB1 budget allocator across lanes, with an information-foraging stop (spec section 6).

UCB1 (`auer2002ucb`) gives each lane its mean reward per call plus an exploration bonus. Round 1
gives every lane a minimum number of calls so every viewpoint is tried; later rounds hand out a block
of calls in proportion to the UCB1 scores. Information foraging (`pirolli1999foraging`): a patch is
left once its yield falls; here a lane closes after K dry rounds unless new verified facts open keys.
"""
from __future__ import annotations

import math

from pydantic import BaseModel, Field

UCB_C = math.sqrt(2)
MIN_FIRST_ROUND = 3
DRY_ROUNDS = 3


class LaneStats(BaseModel):
    calls: int = 0
    reward: float = 0.0
    hits: int = 0
    empties: int = 0
    dry_rounds: int = 0
    closed: bool = False
    prior: float = 0.5


class Allocator(BaseModel):
    lanes: dict[str, LaneStats] = Field(default_factory=dict)
    round: int = 0

    def total_calls(self) -> int:
        return sum(s.calls for s in self.lanes.values())

    def ucb(self, lane: str) -> float:
        s = self.lanes[lane]
        n_tot = max(1, self.total_calls())
        mean = s.reward / s.calls if s.calls else s.prior
        return mean + UCB_C * math.sqrt(math.log(n_tot + 1) / (1 + s.calls))

    def allocate(self, budget_left: int, block: int, open_lanes: list[str]) -> dict[str, int]:
        """Calls per lane for the next round. Never more than budget_left in total."""
        lanes = [l for l in open_lanes if l in self.lanes and not self.lanes[l].closed]
        if budget_left <= 0 or not lanes:
            return {}
        if self.round == 0:
            out, left = {}, budget_left
            for l in sorted(lanes, key=lambda x: -self.lanes[x].prior):
                k = min(MIN_FIRST_ROUND, left)
                if k <= 0:
                    break
                out[l] = k
                left -= k
            return out
        block = min(block, budget_left)
        scores = {l: self.ucb(l) for l in lanes}
        tot = sum(scores.values()) or 1.0
        raw = {l: block * scores[l] / tot for l in lanes}
        out = {l: int(math.floor(v)) for l, v in raw.items()}
        rest = block - sum(out.values())
        for l in sorted(lanes, key=lambda x: (-(raw[x] - out[x]), -scores[x], x)):
            if rest <= 0:
                break
            out[l] += 1
            rest -= 1
        return {l: k for l, k in out.items() if k > 0}

    def update(self, lane: str, calls: int, reward: float, hits: int, empties: int) -> None:
        s = self.lanes[lane]
        s.calls += calls
        s.reward += reward
        s.hits += hits
        s.empties += empties
        if calls and reward <= 0:
            s.dry_rounds += 1
            if s.dry_rounds >= DRY_ROUNDS:
                s.closed = True
        elif reward > 0:
            s.dry_rounds = 0

    def reopen(self, lane: str) -> None:
        if lane in self.lanes:
            self.lanes[lane].closed, self.lanes[lane].dry_rounds = False, 0
