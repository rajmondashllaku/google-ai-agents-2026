"""Deterministic safety checks for every candidate farm action."""

from __future__ import annotations

from math import isclose

from .models import (
    ActionType,
    CROP_CATALOG,
    Decision,
    FarmState,
    ValidationResult,
    ValidationStatus,
)

MAX_SPEND_FRACTION = 0.40
VOLATILITY_THRESHOLD = 0.15
IRRIGATION_UNIT_COST = 20.0
IRRIGATION_MOISTURE_GAIN = 0.20
IRRIGATION_MAX_USEFUL_MOISTURE = 0.70
HIGH_RAIN_PROBABILITY = 0.65
MONEY_TOLERANCE = 0.01

_CROP_ACTIONS = {
    ActionType.BUY_SEEDS,
    ActionType.PLANT,
    ActionType.HARVEST,
    ActionType.SELL,
}
_VOLATILITY_PROTECTED_ACTIONS = {
    ActionType.BUY_SEEDS,
    ActionType.PLANT,
    ActionType.SELL,
}


def _format_percent(value: float) -> str:
    text = f"{value * 100:.2f}".rstrip("0")
    if text.endswith("."):
        text += "0"
    return text


def _result(
    status: ValidationStatus,
    reason: str,
    *,
    actual_cost: float = 0.0,
    max_spend: float,
) -> ValidationResult:
    return ValidationResult(
        status=status,
        reason=reason,
        actual_cost=round(actual_cost, 2),
        max_spend=round(max_spend, 2),
    )


def _expected_cost(decision: Decision) -> float:
    if decision.action is ActionType.BUY_SEEDS and decision.crop in CROP_CATALOG:
        return CROP_CATALOG[decision.crop].seed_cost * (decision.quantity or 0)
    if decision.action is ActionType.IRRIGATE:
        return IRRIGATION_UNIT_COST * (decision.quantity or 0)
    return 0.0


def validate_decision(state: FarmState, decision: Decision) -> ValidationResult:
    """Validate a candidate without mutating state."""
    max_spend = round(state.cash * MAX_SPEND_FRACTION, 2)

    if decision.action in _CROP_ACTIONS:
        if not decision.crop:
            return _result(
                ValidationStatus.REJECTED,
                f"{decision.action.value} requires a crop.",
                max_spend=max_spend,
            )
        if decision.crop not in CROP_CATALOG:
            return _result(
                ValidationStatus.REJECTED,
                f"Unknown crop '{decision.crop}'.",
                max_spend=max_spend,
            )

    if decision.action is ActionType.IRRIGATE and decision.crop is not None:
        if decision.crop not in CROP_CATALOG:
            return _result(
                ValidationStatus.REJECTED,
                f"Unknown crop '{decision.crop}'.",
                max_spend=max_spend,
            )

    if decision.action not in {ActionType.WAIT}:
        if decision.quantity is None or decision.quantity <= 0:
            return _result(
                ValidationStatus.REJECTED,
                f"{decision.action.value} requires a positive quantity.",
                max_spend=max_spend,
            )

    if decision.crop:
        change = abs(state.market_change(decision.crop))
        is_protected_action = decision.action in _VOLATILITY_PROTECTED_ACTIONS
        is_explicit_wait = decision.action is ActionType.WAIT
        if (is_protected_action or is_explicit_wait) and (
            change > VOLATILITY_THRESHOLD + 1e-12
        ):
            return _result(
                ValidationStatus.PAUSED,
                (
                    f"{decision.crop} price changed {_format_percent(change)}%, exceeding "
                    f"the {VOLATILITY_THRESHOLD * 100:.1f}% volatility threshold; "
                    "buy, plant, and sell actions are paused for this crop."
                ),
                max_spend=max_spend,
            )

    expected_cost = _expected_cost(decision)
    if decision.estimated_cost < 0:
        return _result(
            ValidationStatus.REJECTED,
            "Estimated cost cannot be negative.",
            actual_cost=expected_cost,
            max_spend=max_spend,
        )
    if not isclose(
        decision.estimated_cost,
        expected_cost,
        abs_tol=MONEY_TOLERANCE,
    ):
        return _result(
            ValidationStatus.REJECTED,
            (
                f"Estimated cost ${decision.estimated_cost:.2f} does not match "
                f"the deterministic cost ${expected_cost:.2f}."
            ),
            actual_cost=expected_cost,
            max_spend=max_spend,
        )
    if expected_cost > state.cash + MONEY_TOLERANCE:
        return _result(
            ValidationStatus.REJECTED,
            (
                f"Expense ${expected_cost:.2f} exceeds available cash "
                f"${state.cash:.2f}."
            ),
            actual_cost=expected_cost,
            max_spend=max_spend,
        )
    if expected_cost > max_spend + MONEY_TOLERANCE:
        return _result(
            ValidationStatus.REJECTED,
            (
                f"Expense ${expected_cost:.2f} exceeds the 40% spending limit "
                f"of ${max_spend:.2f}."
            ),
            actual_cost=expected_cost,
            max_spend=max_spend,
        )

    if decision.action is ActionType.PLANT:
        assert decision.crop is not None and decision.quantity is not None
        available = state.seed_inventory.get(decision.crop, 0)
        if decision.quantity > available:
            return _result(
                ValidationStatus.REJECTED,
                (
                    f"Cannot plant {decision.quantity} {decision.crop} seed units; "
                    f"only {available} are available."
                ),
                max_spend=max_spend,
            )
        crop = CROP_CATALOG[decision.crop]
        if state.soil_moisture < crop.water_need:
            return _result(
                ValidationStatus.REJECTED,
                (
                    f"Soil moisture {state.soil_moisture:.2f} is below "
                    f"{decision.crop}'s {crop.water_need:.2f} requirement."
                ),
                max_spend=max_spend,
            )
        if state.soil_nutrients < crop.nutrient_need:
            return _result(
                ValidationStatus.REJECTED,
                (
                    f"Soil nutrients {state.soil_nutrients:.2f} are below "
                    f"{decision.crop}'s {crop.nutrient_need:.2f} requirement."
                ),
                max_spend=max_spend,
            )

    if decision.action is ActionType.HARVEST:
        assert decision.crop is not None and decision.quantity is not None
        mature = state.mature_quantity(decision.crop)
        if decision.quantity > mature:
            return _result(
                ValidationStatus.REJECTED,
                (
                    f"Cannot harvest {decision.quantity} {decision.crop} seed units; "
                    f"only {mature} are mature."
                ),
                max_spend=max_spend,
            )

    if decision.action is ActionType.SELL:
        assert decision.crop is not None and decision.quantity is not None
        available = state.inventory.get(decision.crop, 0)
        if decision.quantity > available:
            return _result(
                ValidationStatus.REJECTED,
                (
                    f"Cannot sell {decision.quantity} {decision.crop} units; "
                    f"only {available} are in inventory."
                ),
                max_spend=max_spend,
            )

    if decision.action is ActionType.IRRIGATE:
        if state.soil_moisture >= IRRIGATION_MAX_USEFUL_MOISTURE:
            return _result(
                ValidationStatus.REJECTED,
                (
                    f"Irrigation has no meaningful effect at soil moisture "
                    f"{state.soil_moisture:.2f}."
                ),
                actual_cost=expected_cost,
                max_spend=max_spend,
            )
        if state.weather.rain_probability >= HIGH_RAIN_PROBABILITY:
            return _result(
                ValidationStatus.REJECTED,
                (
                    f"Irrigation is unnecessary with rain probability "
                    f"{state.weather.rain_probability * 100:.0f}%."
                ),
                actual_cost=expected_cost,
                max_spend=max_spend,
            )

    if expected_cost:
        reason = (
            f"Expense ${expected_cost:.2f} is within the 40% spending limit "
            f"of ${max_spend:.2f}."
        )
    elif decision.action is ActionType.WAIT:
        reason = "WAIT is safe and does not change farm resources."
    else:
        reason = "No spending is required and all inventory, field, and maturity checks passed."
    return _result(
        ValidationStatus.APPROVED,
        reason,
        actual_cost=expected_cost,
        max_spend=max_spend,
    )
