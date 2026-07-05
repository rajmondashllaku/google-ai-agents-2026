"""Scenario loading and observation helpers for the local simulator."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import CROP_CATALOG

DEFAULT_SCENARIO_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "sample_scenarios.json"
)


@dataclass(frozen=True)
class ScenarioStep:
    rain_probability: float
    temperature_c: float
    weather_summary: str
    soil_moisture: float
    soil_nutrients: float
    market_prices: dict[str, float]
    event: str


def _parse_step(raw: dict[str, Any], scenario: str, index: int) -> ScenarioStep:
    required = {
        "rain_probability",
        "temperature_c",
        "weather_summary",
        "soil_moisture",
        "soil_nutrients",
        "market_prices",
        "event",
    }
    missing = required.difference(raw)
    if missing:
        names = ", ".join(sorted(missing))
        raise ValueError(f"{scenario} block {index} is missing: {names}")

    prices = {str(crop): float(price) for crop, price in raw["market_prices"].items()}
    if set(prices) != set(CROP_CATALOG):
        raise ValueError(
            f"{scenario} block {index} must provide prices for "
            f"{', '.join(CROP_CATALOG)}"
        )
    if any(price <= 0 for price in prices.values()):
        raise ValueError(f"{scenario} block {index} contains a non-positive price")

    rain = float(raw["rain_probability"])
    moisture = float(raw["soil_moisture"])
    nutrients = float(raw["soil_nutrients"])
    if not all(0.0 <= value <= 1.0 for value in (rain, moisture, nutrients)):
        raise ValueError(
            f"{scenario} block {index} probabilities and soil values must be 0..1"
        )

    return ScenarioStep(
        rain_probability=rain,
        temperature_c=float(raw["temperature_c"]),
        weather_summary=str(raw["weather_summary"]),
        soil_moisture=moisture,
        soil_nutrients=nutrients,
        market_prices=prices,
        event=str(raw["event"]),
    )


def load_scenarios(
    path: str | Path = DEFAULT_SCENARIO_PATH,
) -> dict[str, list[ScenarioStep]]:
    source = Path(path)
    with source.open(encoding="utf-8") as handle:
        raw_scenarios = json.load(handle)
    if not isinstance(raw_scenarios, dict) or not raw_scenarios:
        raise ValueError("Scenario file must contain a non-empty object")

    scenarios: dict[str, list[ScenarioStep]] = {}
    for name, raw_steps in raw_scenarios.items():
        if not isinstance(raw_steps, list) or not raw_steps:
            raise ValueError(f"Scenario '{name}' must contain at least one block")
        scenarios[str(name)] = [
            _parse_step(raw, str(name), index)
            for index, raw in enumerate(raw_steps, start=1)
        ]
    return scenarios


def get_scenario_step(
    scenarios: dict[str, list[ScenarioStep]],
    scenario: str,
    block_number: int,
) -> ScenarioStep:
    if scenario not in scenarios:
        available = ", ".join(sorted(scenarios))
        raise ValueError(f"Unknown scenario '{scenario}'. Available: {available}")
    if block_number < 1:
        raise ValueError("block_number must be at least 1")
    steps = scenarios[scenario]
    return steps[(block_number - 1) % len(steps)]
