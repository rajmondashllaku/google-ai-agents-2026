"""Offline agent facade that keeps policy selection separate from safety."""

from __future__ import annotations

from .models import Decision, FarmState
from .policy import BaselinePolicy


class KaggricultureAgent:
    """Produces a candidate decision; it is never allowed to apply actions."""

    def __init__(self, policy: BaselinePolicy | None = None) -> None:
        self.policy = policy or BaselinePolicy()

    def choose_action(self, state: FarmState) -> Decision:
        return self.policy.select_action(state)
