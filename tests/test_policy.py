from __future__ import annotations

from copy import deepcopy

from src.models import ActionType, FarmState, WeatherForecast
from src.policy import BaselinePolicy


def test_weather_and_soil_conditions_change_selected_action() -> None:
    policy = BaselinePolicy()
    dry_state = FarmState.initial()
    dry_state.block_number = 1
    dry_state.seed_inventory["wheat"] = 4
    dry_state.soil_moisture = 0.30
    dry_state.soil_nutrients = 0.80
    dry_state.weather = WeatherForecast(
        rain_probability=0.10,
        temperature_c=31.0,
        summary="dry",
    )

    rainy_state = deepcopy(dry_state)
    rainy_state.weather.rain_probability = 0.80
    moist_state = deepcopy(dry_state)
    moist_state.soil_moisture = 0.60

    assert policy.select_action(dry_state).action is ActionType.IRRIGATE
    assert policy.select_action(rainy_state).action is ActionType.WAIT
    assert policy.select_action(moist_state).action is ActionType.PLANT
