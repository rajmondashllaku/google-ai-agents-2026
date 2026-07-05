"""Deterministic baseline policy for selecting one useful action per block."""

from __future__ import annotations

from .guardrails import (
    IRRIGATION_UNIT_COST,
    VOLATILITY_THRESHOLD,
)
from .models import ActionType, CROP_CATALOG, Decision, FarmState


class BaselinePolicy:
    """A conservative offline policy; guardrails remain the final authority."""

    def select_action(self, state: FarmState) -> Decision:
        candidate = self._preferred_action(state)
        if (
            candidate.crop
            and candidate.action
            in {ActionType.BUY_SEEDS, ActionType.PLANT, ActionType.SELL}
        ):
            change = abs(state.market_change(candidate.crop))
            if change > VOLATILITY_THRESHOLD + 1e-12:
                return Decision(
                    action=ActionType.WAIT,
                    crop=candidate.crop,
                    estimated_cost=0.0,
                    reason=(
                        f"Pause planned {candidate.action.value}: "
                        f"{candidate.crop} moved {change * 100:.1f}% this block."
                    ),
                    metadata={
                        "volatility_pause": True,
                        "deferred_action": candidate.action.value,
                        "price_change": change,
                    },
                )
        return candidate

    def _preferred_action(self, state: FarmState) -> Decision:
        mature = [
            (crop, state.mature_quantity(crop))
            for crop in CROP_CATALOG
            if state.mature_quantity(crop) > 0
        ]
        if mature:
            crop, quantity = mature[0]
            return Decision(
                action=ActionType.HARVEST,
                crop=crop,
                quantity=quantity,
                estimated_cost=0.0,
                reason=f"{crop} has reached its maturity block.",
                metadata={"confidence": 1.0},
            )

        sellable = [
            crop
            for crop, quantity in state.inventory.items()
            if quantity > 0
            and state.current_market_prices.get(crop, 0.0)
            >= CROP_CATALOG[crop].reference_price
        ]
        if sellable:
            crop = max(
                sellable,
                key=lambda name: (
                    state.current_market_prices[name]
                    / CROP_CATALOG[name].reference_price
                ),
            )
            return Decision(
                action=ActionType.SELL,
                crop=crop,
                quantity=state.inventory[crop],
                estimated_cost=0.0,
                reason=(
                    f"{crop} is mature and its price "
                    f"${state.current_market_prices[crop]:.2f} meets the target."
                ),
                metadata={"confidence": 0.9},
            )

        active_crop = self._active_crop(state)
        if active_crop is not None:
            crop = CROP_CATALOG[active_crop]
            needs_water = state.soil_moisture < crop.water_need
            low_rain = state.weather.rain_probability < 0.45
            if needs_water and low_rain:
                return Decision(
                    action=ActionType.IRRIGATE,
                    crop=active_crop,
                    quantity=1,
                    estimated_cost=IRRIGATION_UNIT_COST,
                    reason=(
                        f"Soil moisture {state.soil_moisture:.2f} is below "
                        f"{active_crop}'s {crop.water_need:.2f} need and rain is unlikely."
                    ),
                    metadata={"confidence": 0.95},
                )

        plantable = [
            crop
            for crop, quantity in state.seed_inventory.items()
            if quantity > 0
            and state.soil_moisture >= CROP_CATALOG[crop].water_need
            and state.soil_nutrients >= CROP_CATALOG[crop].nutrient_need
        ]
        if plantable:
            crop = plantable[0]
            return Decision(
                action=ActionType.PLANT,
                crop=crop,
                quantity=state.seed_inventory[crop],
                estimated_cost=0.0,
                reason="Available seeds match current soil moisture and nutrient conditions.",
                metadata={"confidence": 0.9},
            )

        if active_crop is None:
            crop = self._best_crop(state)
            definition = CROP_CATALOG[crop]
            conservative_budget = min(state.cash * 0.20, state.cash * 0.40)
            quantity = min(4, int(conservative_budget // definition.seed_cost))
            if quantity > 0:
                cost = definition.seed_cost * quantity
                return Decision(
                    action=ActionType.BUY_SEEDS,
                    crop=crop,
                    quantity=quantity,
                    estimated_cost=cost,
                    reason=(
                        f"Acquire a small {crop} seed lot for "
                        f"{cost / state.cash * 100:.1f}% of available cash."
                    ),
                    metadata={"confidence": 0.8},
                )

        return Decision(
            action=ActionType.WAIT,
            estimated_cost=0.0,
            reason="No safe, useful farm action is available this block.",
            metadata={"confidence": 1.0},
        )

    @staticmethod
    def _active_crop(state: FarmState) -> str | None:
        for planted in state.planted_crops:
            return planted.crop
        for crop, quantity in state.seed_inventory.items():
            if quantity > 0:
                return crop
        return None

    @staticmethod
    def _best_crop(state: FarmState) -> str:
        return max(
            CROP_CATALOG,
            key=lambda crop: (
                state.current_market_prices.get(
                    crop,
                    CROP_CATALOG[crop].reference_price,
                )
                * CROP_CATALOG[crop].yield_per_seed
                - CROP_CATALOG[crop].seed_cost
            ),
        )
