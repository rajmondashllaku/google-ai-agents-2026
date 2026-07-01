def get_market_prices():
    """Returns the current market asset price deltas."""
    return {"soybeans": +0.02, "corn": -0.01, "wheat": +0.05}

def get_weather_deltas():
    """Returns the latest weather vector deltas."""
    return {"temperature": +1.2, "precipitation": -0.5}

def get_soil_moisture():
    """Returns the current soil moisture data."""
    return {"zone_A": 0.45, "zone_B": 0.38}
