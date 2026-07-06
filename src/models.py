"""Typed domain models for the offline farm simulation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ActionType(str, Enum):
    WAIT = "WAIT"
    BUY_SEEDS = "BUY_SEEDS"
    PLANT = "PLANT"
    IRRIGATE = "IRRIGATE"
    HARVEST = "HARVEST"
    SELL = "SELL"


class ValidationStatus(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PAUSED = "PAUSED"


@dataclass(frozen=True)
class CropDefinition:
    name: str
    seed_cost: float
    blocks_to_maturity: int
    yield_per_seed: int
    water_need: float
    nutrient_need: float
    reference_price: float


CROP_CATALOG: dict[str, CropDefinition] = {
    "wheat": CropDefinition(
        name="wheat",
        seed_cost=40.0,
        blocks_to_maturity=2,
        yield_per_seed=6,
        water_need=0.50,
        nutrient_need=0.50,
        reference_price=12.0,
    ),
    "corn": CropDefinition(
        name="corn",
        seed_cost=30.0,
        blocks_to_maturity=3,
        yield_per_seed=5,
        water_need=0.42,
        nutrient_need=0.55,
        reference_price=9.0,
    ),
}


@dataclass
class WeatherForecast:
    rain_probability: float = 0.0
    temperature_c: float = 20.0
    summary: str = "unknown"


@dataclass
class PlantedCrop:
    crop: str
    quantity: int
    planted_block: int

    def age(self, current_block: int) -> int:
        return max(0, current_block - self.planted_block)

    def is_mature(self, current_block: int) -> bool:
        return self.age(current_block) >= CROP_CATALOG[self.crop].blocks_to_maturity


@dataclass
class Decision:
    action: ActionType
    crop: str | None = None
    quantity: int | None = None
    estimated_cost: float = 0.0
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationResult:
    status: ValidationStatus
    reason: str
    actual_cost: float = 0.0
    max_spend: float = 0.0

    @property
    def approved(self) -> bool:
        return self.status is ValidationStatus.APPROVED


@dataclass
class DecisionRecord:
    block_number: int
    decision: Decision
    validation: ValidationResult
    applied_action: ActionType
    result: str


@dataclass(frozen=True)
class BlockSnapshot:
    block_number: int
    cash: float
    soil_moisture: float
    soil_nutrients: float
    rain_probability: float
    temperature_c: float
    weather_summary: str
    market_prices: dict[str, float]
    seed_inventory: dict[str, int]
    inventory: dict[str, int]
    planted_quantity: int


@dataclass
class FarmState:
    block_number: int
    cash: float
    seed_inventory: dict[str, int]
    inventory: dict[str, int]
    planted_crops: list[PlantedCrop]
    soil_moisture: float
    soil_nutrients: float
    weather: WeatherForecast
    current_market_prices: dict[str, float]
    previous_market_prices: dict[str, float]
    decision_history: list[DecisionRecord] = field(default_factory=list)
    event_logs: list[str] = field(default_factory=list)

    @classmethod
    def initial(
        cls,
        cash: float = 1_000.0,
        market_prices: dict[str, float] | None = None,
    ) -> "FarmState":
        prices = market_prices or {
            name: crop.reference_price for name, crop in CROP_CATALOG.items()
        }
        return cls(
            block_number=0,
            cash=float(cash),
            seed_inventory={name: 0 for name in CROP_CATALOG},
            inventory={name: 0 for name in CROP_CATALOG},
            planted_crops=[],
            soil_moisture=0.5,
            soil_nutrients=0.7,
            weather=WeatherForecast(),
            current_market_prices=dict(prices),
            previous_market_prices=dict(prices),
        )

    def market_change(self, crop: str) -> float:
        """Return the signed price change as a decimal (0.15 means 15%)."""
        current = self.current_market_prices.get(crop)
        previous = self.previous_market_prices.get(crop)
        if current is None or previous is None or previous <= 0:
            return 0.0
        return (current - previous) / previous

    def mature_quantity(self, crop: str) -> int:
        return sum(
            planted.quantity
            for planted in self.planted_crops
            if planted.crop == crop and planted.is_mature(self.block_number)
        )

    def resource_snapshot(self) -> tuple[Any, ...]:
        """Immutable resource view used to verify rejected actions do not mutate state."""
        planted = tuple(
            (item.crop, item.quantity, item.planted_block)
            for item in self.planted_crops
        )
        return (
            round(self.cash, 2),
            tuple(sorted(self.seed_inventory.items())),
            tuple(sorted(self.inventory.items())),
            planted,
            round(self.soil_moisture, 4),
            round(self.soil_nutrients, 4),
        )
