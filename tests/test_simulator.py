from __future__ import annotations

from dataclasses import asdict

import pytest

from src.models import ActionType, Decision, FarmState, ValidationStatus
from src.simulator import FarmSimulator


class SellAgent:
    def choose_action(self, state: FarmState) -> Decision:
        return Decision(
            action=ActionType.SELL,
            crop="wheat",
            quantity=3,
            estimated_cost=0.0,
            reason="Test an approved sale.",
        )


def test_selling_updates_cash_and_inventory() -> None:
    simulator = FarmSimulator(
        scenario="normal_growth",
        blocks=1,
        agent=SellAgent(),  # type: ignore[arg-type]
    )
    simulator.state.inventory["wheat"] = 3

    result = simulator.run(verbose=False)

    assert result.state.cash == pytest.approx(1_036.0)
    assert result.state.inventory["wheat"] == 0
    assert result.state.decision_history[0].applied_action is ActionType.SELL


def test_market_spike_completes_without_unsafe_transactions() -> None:
    result = FarmSimulator(
        scenario="market_spike",
        blocks=10,
        seed=7,
    ).run(verbose=False)

    assert result.unsafe_transactions == 0
    assert result.volatility_pauses >= 1
    spike_record = result.state.decision_history[4]
    assert spike_record.validation.status is ValidationStatus.PAUSED
    assert spike_record.applied_action is ActionType.WAIT
    assert "20.0%" in spike_record.validation.reason


def test_simulation_is_deterministic_for_same_seed_and_scenario() -> None:
    first = FarmSimulator(
        scenario="drought",
        blocks=10,
        seed=123,
    ).run(verbose=False)
    second = FarmSimulator(
        scenario="drought",
        blocks=10,
        seed=123,
    ).run(verbose=False)

    assert asdict(first) == asdict(second)
