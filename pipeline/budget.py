"""Per-stage wall-clock budgets.

Tiny utility shared by stages that loop over N items (summarize,
ensure_embeddings). The watchdog tracks elapsed time and answers a single
question: has this stage exceeded its allotted wall-clock budget?

Why not signal-based timeouts? `signal.alarm` doesn't compose with sub-
processes / threads / asyncio. Cooperative budget polling between loop
iterations is simpler, portable, and lets the stage commit partial work
before bailing.

Budgets are env-configurable so the operator can tune them per-machine
without code changes:

    BUDGET_SUMMARIZE_SEC          default 3600  (60 min)
    BUDGET_ENSURE_EMBEDDINGS_SEC  default 1800  (30 min)

Set a value to 0 to disable the budget entirely.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)

# Defaults are generous on purpose — they catch genuinely-stuck loops,
# not slow-but-progressing ones. Tighten via env per-machine.
_DEFAULTS: dict[str, int] = {
    "summarize":         3600,  # 60 min
    "ensure_embeddings": 1800,  # 30 min
}


@dataclass
class BudgetWatch:
    """Track elapsed time against a stage's wall-clock budget.

    Usage:
        watch = BudgetWatch.for_stage("summarize")
        for item in items:
            if watch.exceeded():
                # log + bail; partial work is fine
                break
            process(item)
    """
    label: str
    budget_seconds: float           # 0 disables the watch
    started_at: float

    @classmethod
    def for_stage(cls, label: str) -> "BudgetWatch":
        env_key = f"BUDGET_{label.upper()}_SEC"
        try:
            seconds = float(os.environ.get(env_key, _DEFAULTS.get(label, 0)))
        except (TypeError, ValueError):
            seconds = _DEFAULTS.get(label, 0)
        if seconds < 0:
            seconds = 0
        return cls(label=label, budget_seconds=seconds, started_at=time.monotonic())

    def elapsed(self) -> float:
        return time.monotonic() - self.started_at

    def exceeded(self) -> bool:
        if self.budget_seconds <= 0:
            return False
        return self.elapsed() >= self.budget_seconds

    def log_exceeded(self, *, remaining_items: int = 0) -> None:
        """Log a consistent message when the budget trips. Idempotent — the
        caller should only invoke this on the iteration that detected the
        trip, not in subsequent skipped iterations."""
        log.warning(
            "Stage %r budget exceeded: %.0fs >= %.0fs; bailing with %d item(s) deferred",
            self.label, self.elapsed(), self.budget_seconds, remaining_items,
        )
