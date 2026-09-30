"""Risk rules applied to every strategy's output before any order is placed."""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import RiskConfig


@dataclass
class RiskDecision:
    weights: dict[str, float]
    halt: bool = False
    notes: list[str] = field(default_factory=list)


class RiskManager:
    def __init__(self, cfg: RiskConfig):
        self.cfg = cfg

    def apply(self, weights: dict[str, float], equity: float, peak_equity: float) -> RiskDecision:
        notes: list[str] = []

        if peak_equity > 0:
            drawdown = 1 - equity / peak_equity
            if drawdown >= self.cfg.max_drawdown:
                notes.append(
                    f"Drawdown {drawdown:.1%} hit the {self.cfg.max_drawdown:.0%} limit: "
                    "liquidating and halting."
                )
                return RiskDecision({}, halt=True, notes=notes)

        clean = {s: float(w) for s, w in weights.items() if w and w > 0}
        cap = self.cfg.max_position_weight
        for s, w in clean.items():
            if w > cap:
                notes.append(f"{s}: capped {w:.1%} -> {cap:.1%}")
                clean[s] = cap

        budget = 1 - self.cfg.min_cash_weight
        total = sum(clean.values())
        if total > budget:
            scale = budget / total
            clean = {s: w * scale for s, w in clean.items()}
            notes.append(f"Scaled weights by {scale:.3f} to keep {self.cfg.min_cash_weight:.0%} cash")
        return RiskDecision(clean, notes=notes)
