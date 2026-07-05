"""Block-by-block deterministic farm simulation engine."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .agent import KaggricultureAgent
from .guardrails import IRRIGATION_MOISTURE_GAIN, validate_decision
from .models import (
    ActionType,
    CROP_CATALOG,
    Decision,
    DecisionRecord,
    FarmState,
    PlantedCrop,
    ValidationResult,
    ValidationStatus,
    WeatherForecast,
)
from .tools import (
    DEFAULT_SCENARIO_PATH,
    ScenarioStep,
    get_scenario_step,
    load_scenarios,
)


@dataclass
class SimulationResult:
    scenario: str
    seed: int
    blocks_run: int
    starting_cash: float
    state: FarmState
    approved_decisions: int
    rejected_decisions: int
    volatility_pauses: int
    unsafe_transactions: int


class FarmSimulator:
    def __init__(
        self,
        scenario: str = "normal_growth",
        blocks: int = 10,
        *,
        seed: int = 42,
        initial_cash: float = 1_000.0,
        scenario_path: str | Path = DEFAULT_SCENARIO_PATH,
        agent: KaggricultureAgent | None = None,
    ) -> None:
        if blocks < 1:
            raise ValueError("blocks must be at least 1")
        self.scenarios = load_scenarios(scenario_path)
        if scenario not in self.scenarios:
            available = ", ".join(sorted(self.scenarios))
            raise ValueError(f"Unknown scenario '{scenario}'. Available: {available}")
        first_prices = self.scenarios[scenario][0].market_prices
        self.state = FarmState.initial(cash=initial_cash, market_prices=first_prices)
        self.scenario = scenario
        self.blocks = blocks
        self.seed = seed
        self.agent = agent or KaggricultureAgent()

    def run(
        self,
        *,
        verbose: bool = True,
        output: Callable[[str], None] = print,
    ) -> SimulationResult:
        approved = 0
        rejected = 0
        paused = 0
        unsafe = 0
        starting_cash = self.state.cash

        for block_number in range(1, self.blocks + 1):
            step = get_scenario_step(
                self.scenarios,
                self.scenario,
                block_number,
            )
            self._observe(block_number, step)
            candidate = self.agent.choose_action(self.state)
            resources_before = self.state.resource_snapshot()
            validation = validate_decision(self.state, candidate)

            if validation.approved:
                result_text = self._apply(candidate, validation)
                applied_action = candidate.action
                approved += 1
            else:
                applied_action = ActionType.WAIT
                result_text = (
                    f"WAIT; candidate not applied; cash unchanged at "
                    f"${self.state.cash:.2f}."
                )
                if validation.status is ValidationStatus.PAUSED:
                    paused += 1
                else:
                    rejected += 1
                if self.state.resource_snapshot() != resources_before:
                    unsafe += 1

            record = DecisionRecord(
                block_number=block_number,
                decision=candidate,
                validation=validation,
                applied_action=applied_action,
                result=result_text,
            )
            self.state.decision_history.append(record)
            self.state.event_logs.extend(
                [
                    f"Block {block_number}: {step.event}",
                    (
                        f"Guardrail {validation.status.value}: "
                        f"{validation.reason}"
                    ),
                    f"Result: {result_text}",
                ]
            )
            if verbose:
                self._print_block(step, record, output)

        result = SimulationResult(
            scenario=self.scenario,
            seed=self.seed,
            blocks_run=self.blocks,
            starting_cash=starting_cash,
            state=self.state,
            approved_decisions=approved,
            rejected_decisions=rejected,
            volatility_pauses=paused,
            unsafe_transactions=unsafe,
        )
        if verbose:
            self._print_summary(result, output)
        return result

    def _observe(self, block_number: int, step: ScenarioStep) -> None:
        self.state.block_number = block_number
        self.state.previous_market_prices = dict(self.state.current_market_prices)
        self.state.current_market_prices = dict(step.market_prices)
        self.state.soil_moisture = step.soil_moisture
        self.state.soil_nutrients = step.soil_nutrients
        self.state.weather = WeatherForecast(
            rain_probability=step.rain_probability,
            temperature_c=step.temperature_c,
            summary=step.weather_summary,
        )

    def _apply(
        self,
        decision: Decision,
        validation: ValidationResult,
    ) -> str:
        if decision.action is ActionType.WAIT:
            return f"WAIT; cash unchanged at ${self.state.cash:.2f}."

        assert decision.quantity is not None
        if decision.action is ActionType.BUY_SEEDS:
            assert decision.crop is not None
            self.state.cash = round(self.state.cash - validation.actual_cost, 2)
            self.state.seed_inventory[decision.crop] += decision.quantity
            return (
                f"bought {decision.quantity} {decision.crop} seed units; "
                f"cash ${self.state.cash:.2f}."
            )

        if decision.action is ActionType.PLANT:
            assert decision.crop is not None
            self.state.seed_inventory[decision.crop] -= decision.quantity
            self.state.planted_crops.append(
                PlantedCrop(
                    crop=decision.crop,
                    quantity=decision.quantity,
                    planted_block=self.state.block_number,
                )
            )
            return (
                f"planted {decision.quantity} {decision.crop} seed units; "
                f"cash ${self.state.cash:.2f}."
            )

        if decision.action is ActionType.IRRIGATE:
            self.state.cash = round(self.state.cash - validation.actual_cost, 2)
            self.state.soil_moisture = min(
                1.0,
                self.state.soil_moisture
                + IRRIGATION_MOISTURE_GAIN * decision.quantity,
            )
            return (
                f"soil irrigated to {self.state.soil_moisture:.2f}; "
                f"cash ${self.state.cash:.2f}."
            )

        if decision.action is ActionType.HARVEST:
            assert decision.crop is not None
            remaining_to_harvest = decision.quantity
            remaining_plants: list[PlantedCrop] = []
            for planted in self.state.planted_crops:
                can_harvest = (
                    planted.crop == decision.crop
                    and planted.is_mature(self.state.block_number)
                    and remaining_to_harvest > 0
                )
                if not can_harvest:
                    remaining_plants.append(planted)
                    continue
                harvested = min(planted.quantity, remaining_to_harvest)
                remaining_to_harvest -= harvested
                leftover = planted.quantity - harvested
                if leftover:
                    remaining_plants.append(
                        PlantedCrop(
                            crop=planted.crop,
                            quantity=leftover,
                            planted_block=planted.planted_block,
                        )
                    )
            self.state.planted_crops = remaining_plants
            produced = (
                decision.quantity * CROP_CATALOG[decision.crop].yield_per_seed
            )
            self.state.inventory[decision.crop] += produced
            return (
                f"harvested {decision.quantity} {decision.crop} seed units into "
                f"{produced} crop units; cash ${self.state.cash:.2f}."
            )

        if decision.action is ActionType.SELL:
            assert decision.crop is not None
            price = self.state.current_market_prices[decision.crop]
            revenue = round(price * decision.quantity, 2)
            self.state.inventory[decision.crop] -= decision.quantity
            self.state.cash = round(self.state.cash + revenue, 2)
            return (
                f"sold {decision.quantity} {decision.crop} units for "
                f"${revenue:.2f}; cash ${self.state.cash:.2f}."
            )

        raise ValueError(f"Unsupported action: {decision.action}")

    def _print_block(
        self,
        step: ScenarioStep,
        record: DecisionRecord,
        output: Callable[[str], None],
    ) -> None:
        market = ", ".join(
            f"{crop} {self.state.market_change(crop) * 100:+.1f}%"
            for crop in CROP_CATALOG
        )
        nutrients = "adequate" if self.state.soil_nutrients >= 0.5 else "low"
        candidate = record.decision.action.value
        if record.decision.crop:
            candidate += f" {record.decision.crop}"
        if record.decision.quantity is not None:
            candidate += f" x{record.decision.quantity}"
        output(f"\nBlock {record.block_number}")
        output(
            f"Weather: {step.weather_summary}, rain probability "
            f"{step.rain_probability * 100:.0f}%, {step.temperature_c:.1f}C"
        )
        output(
            f"Soil: moisture {step.soil_moisture:.2f}, "
            f"nutrients {nutrients} ({step.soil_nutrients:.2f})"
        )
        output(f"Market: {market}")
        output(
            f"Candidate: {candidate}, estimated cost "
            f"${record.decision.estimated_cost:.2f} -- {record.decision.reason}"
        )
        output(
            f"Guardrails: {record.validation.status.value} -- "
            f"{record.validation.reason}"
        )
        output(f"Result: {record.result}")

    @staticmethod
    def _print_summary(
        result: SimulationResult,
        output: Callable[[str], None],
    ) -> None:
        state = result.state
        planted = sum(item.quantity for item in state.planted_crops)
        output("\nFinal summary")
        output(
            f"Scenario: {result.scenario} | Blocks: {result.blocks_run} | "
            f"Seed: {result.seed}"
        )
        output(
            f"Cash: ${result.starting_cash:.2f} -> ${state.cash:.2f} | "
            f"Harvest inventory: {sum(state.inventory.values())} | "
            f"Planted seed units: {planted}"
        )
        output(
            f"Approved: {result.approved_decisions} | "
            f"Rejected: {result.rejected_decisions} | "
            f"Volatility pauses: {result.volatility_pauses} | "
            f"Unsafe transactions: {result.unsafe_transactions}"
        )
