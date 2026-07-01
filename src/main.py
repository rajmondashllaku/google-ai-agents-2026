import asyncio
import sys

try:
    from google.adk import InMemoryRunner
except ImportError:
    # Mock fallback for google.adk if not installed
    class InMemoryRunner:
        pass

class StateTracker:
    def __init__(self, initial_capital):
        self.capital = initial_capital
        self.block = 0

def before_model_callback(state, budget_request=None):
    """
    Mock fallback safety gate callback.
    Enforces the <= 40% capital allocation boundary.
    """
    max_budget = state.capital * 0.40
    return max_budget

async def run_blocks():
    """
    Core asynchronous engine and 5-block automated runtime loop.
    """
    state = StateTracker(1000.0)
    runner = InMemoryRunner()

    print(f"- **Starting Capital**: ${state.capital:,.2f}")

    for i in range(1, 6):
        state.block = i

        # Sequential telemetry checks as per SKILL.md rules
        import tools
        weather = tools.get_weather_deltas()
        soil = tools.get_soil_moisture()
        market = tools.get_market_prices()

        # Mock safety gate evaluating the budget
        budget = before_model_callback(state)
        state.capital -= budget

        print(f"- **Block {i}**: Budget ${budget:.2f} | Remaining ${state.capital:.2f}")

    print(f"- **Final Capital**: ${state.capital:.2f}")

if __name__ == "__main__":
    asyncio.run(run_blocks())
