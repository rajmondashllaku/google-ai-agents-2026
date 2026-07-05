from __future__ import annotations

from src.guardrails import validate_decision
from src.models import (
    ActionType,
    Decision,
    FarmState,
    PlantedCrop,
    ValidationStatus,
)


def make_state() -> FarmState:
    state = FarmState.initial(cash=1_000.0)
    state.block_number = 2
    state.soil_moisture = 0.75
    state.soil_nutrients = 0.80
    return state


def test_spending_exactly_40_percent_is_allowed() -> None:
    state = make_state()
    decision = Decision(
        action=ActionType.BUY_SEEDS,
        crop="wheat",
        quantity=10,
        estimated_cost=400.0,
        reason="Boundary test.",
    )

    result = validate_decision(state, decision)

    assert result.status is ValidationStatus.APPROVED
    assert result.max_spend == 400.0


def test_spending_over_40_percent_is_rejected_with_reason() -> None:
    state = make_state()
    decision = Decision(
        action=ActionType.BUY_SEEDS,
        crop="wheat",
        quantity=11,
        estimated_cost=440.0,
        reason="Overspend test.",
    )

    result = validate_decision(state, decision)

    assert result.status is ValidationStatus.REJECTED
    assert "40% spending limit" in result.reason
    assert "$400.00" in result.reason


def test_price_movement_at_15_percent_is_allowed() -> None:
    state = make_state()
    state.previous_market_prices["wheat"] = 100.0
    state.current_market_prices["wheat"] = 115.0
    decision = Decision(
        action=ActionType.BUY_SEEDS,
        crop="wheat",
        quantity=1,
        estimated_cost=40.0,
        reason="Boundary volatility test.",
    )

    result = validate_decision(state, decision)

    assert result.status is ValidationStatus.APPROVED


def test_price_movement_above_15_percent_pauses_transaction() -> None:
    state = make_state()
    state.previous_market_prices["wheat"] = 100.0
    state.current_market_prices["wheat"] = 115.01
    decision = Decision(
        action=ActionType.SELL,
        crop="wheat",
        quantity=1,
        estimated_cost=0.0,
        reason="Volatility test.",
    )
    state.inventory["wheat"] = 1

    result = validate_decision(state, decision)

    assert result.status is ValidationStatus.PAUSED
    assert "15.0% volatility threshold" in result.reason
    assert "15.01%" in result.reason


def test_planting_without_seeds_is_rejected() -> None:
    state = make_state()
    decision = Decision(
        action=ActionType.PLANT,
        crop="wheat",
        quantity=1,
        estimated_cost=0.0,
        reason="No seed test.",
    )

    result = validate_decision(state, decision)

    assert result.status is ValidationStatus.REJECTED
    assert "only 0 are available" in result.reason


def test_harvesting_before_maturity_is_rejected() -> None:
    state = make_state()
    state.planted_crops.append(
        PlantedCrop(crop="wheat", quantity=2, planted_block=1)
    )
    decision = Decision(
        action=ActionType.HARVEST,
        crop="wheat",
        quantity=2,
        estimated_cost=0.0,
        reason="Early harvest test.",
    )

    result = validate_decision(state, decision)

    assert result.status is ValidationStatus.REJECTED
    assert "only 0 are mature" in result.reason


def test_buying_beyond_available_cash_is_rejected() -> None:
    state = make_state()
    state.cash = 50.0
    decision = Decision(
        action=ActionType.BUY_SEEDS,
        crop="wheat",
        quantity=2,
        estimated_cost=80.0,
        reason="Insufficient cash test.",
    )

    result = validate_decision(state, decision)

    assert result.status is ValidationStatus.REJECTED
    assert "exceeds available cash $50.00" in result.reason


def test_selling_more_than_inventory_is_rejected() -> None:
    state = make_state()
    state.inventory["corn"] = 2
    decision = Decision(
        action=ActionType.SELL,
        crop="corn",
        quantity=3,
        estimated_cost=0.0,
        reason="Inventory test.",
    )

    result = validate_decision(state, decision)

    assert result.status is ValidationStatus.REJECTED
    assert "only 2 are in inventory" in result.reason


def test_irrigating_wet_soil_is_rejected() -> None:
    state = make_state()
    decision = Decision(
        action=ActionType.IRRIGATE,
        crop="wheat",
        quantity=1,
        estimated_cost=20.0,
        reason="Irrigation usefulness test.",
    )

    result = validate_decision(state, decision)

    assert result.status is ValidationStatus.REJECTED
    assert "no meaningful effect" in result.reason
