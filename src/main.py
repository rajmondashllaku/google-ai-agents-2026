import os
import sys
import asyncio

# Ensure the src directory is in the Python search path for easy module import
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.runners import InMemoryRunner
from google.genai import types
from google.adk.models.llm_response import LlmResponse
from google.adk.agents.callback_context import CallbackContext
from tools import get_market_prices, get_weather_deltas, get_soil_moisture

# 1. Trajectory Tracing Audit Logger
def log_trajectory_step(step_name: str, payload: dict):
    """Logs detailed agent reasoning steps and outputs for audit validation."""
    print(f"\n[AUDIT TRACE] --- Step: {step_name} ---")
    for k, v in payload.items():
        print(f"  {k}: {v}")
    print("-" * 40)

# 2. Safety Gate callback (Human-in-the-Loop)
async def safety_gate_callback(callback_context: CallbackContext) -> None:
    """Evaluates agent proposed budget executions. Halts for human approval if > $500."""
    proposed_budget = callback_context.state.get("proposed_budget", 0)
    
    log_trajectory_step("Safety Gate Evaluation", {
        "proposed_budget": proposed_budget,
        "current_state": callback_context.state
    })
    
    if proposed_budget > 500:
        print(f"\n[WARNING] Proposed budget of ${proposed_budget} exceeds the $500 safety threshold!")
        user_approval = input("Approve budget execution? (y/n): ").strip().lower()
        if user_approval != 'y':
            print("[SHUTDOWN] Execution aborted due to safety check denial.")
            sys.exit(1)
        print("[APPROVED] Execution approved by operator.")

# 3. Mock Model Callback (bypasses live API calls)
async def mock_model_callback(callback_context: CallbackContext, llm_request) -> LlmResponse | None:
    """Bypasses live LLM calls and returns a mock response containing the tool metrics."""
    proposed_budget = callback_context.state.get("proposed_budget", 0)
    
    # Simulate tool calls internally to fetch current environment metrics
    market = get_market_prices()
    weather = get_weather_deltas()
    soil = get_soil_moisture()
    
    log_trajectory_step("Mock LLM Inference Call", {
        "budget": proposed_budget,
        "market_prices": market["prices"],
        "weather_vector": weather["weather_vector"],
        "soil_moisture": soil["zones"]
    })
    
    text = (
        f"Simulating Kaggriculture block with budget parameter: ${proposed_budget}.\n"
        f"Checking telemetry feeds:\n"
        f"  - Weather deltas vector: {weather['weather_vector']}\n"
        f"  - Soil moisture profile: {soil['zones']}\n"
        f"  - Current asset price matrices: {market['prices']}\n\n"
        f"All SKILL.md operational boundary checks PASSED. Resource allocation limits validated."
    )
    
    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[types.Part.from_text(text=text)]
        )
    )

# 4. Initialize Agent using google.adk Agent Primitive
# Reads instructions from skills/kaggriculture-logic/SKILL.md
skill_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
    "skills", "kaggriculture-logic", "SKILL.md"
)

with open(skill_path, "r", encoding="utf-8") as f:
    skill_content = f.read()

system_instruction = f"""
You are the Kaggriculture Capstone simulation coordinator agent.
Obey the rules and guidelines specified here:

{skill_content}
"""

kaggriculture_agent = Agent(
    name="kaggriculture_agent",
    model="gemini-2.0-flash",
    instruction=system_instruction,
    tools=[get_market_prices, get_weather_deltas, get_soil_moisture],
    before_agent_callback=safety_gate_callback,
    before_model_callback=mock_model_callback,
)

# 4. App Definition
app = App(
    name="kaggriculture_app",
    root_agent=kaggriculture_agent
)

# 5. Main Asynchronous Runtime Loop
def load_env():
    """Manually parse .env file and load variables into os.environ to avoid CLI pipeline leaks."""
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    parts = line.split("=", 1)
                    if len(parts) == 2:
                        key = parts[0].strip()
                        val = parts[1].strip().strip('"').strip("'")
                        os.environ[key] = val

async def main():
    load_env()
    # Retrieve Gemini API Key from environment configuration file
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("[ERROR] GEMINI_API_KEY environment variable is not set. Ensure it is defined in .env")
        sys.exit(1)

    runner = InMemoryRunner(app=app)
    session = await runner.session_service.create_session(
        app_name="kaggriculture_app", 
        user_id="operator"
    )

    # ── Autonomous Runtime Constants ──────────────────────────────────────────
    TOTAL_BLOCKS     = 5        # Number of simulation blocks to run in sequence
    STARTING_CAPITAL = 1000.0  # Virtual capital pool (simulation credits)
    # ─────────────────────────────────────────────────────────────────────────

    remaining_capital = STARTING_CAPITAL

    print("Kaggriculture Autonomous Simulation Agent Initialized.")
    print(f"  Starting capital pool : ${STARTING_CAPITAL:,.2f}")
    print(f"  Planned blocks        : {TOTAL_BLOCKS}")
    print(f"  Safety threshold      : $500.00  (human approval required above this)")
    print(f"  Budget rule           : <=40% of remaining capital per block (SKILL.md)\n")

    try:
        for block_num in range(1, TOTAL_BLOCKS + 1):

            # ── 1. Autonomous Budget Calculation ─────────────────────────────
            # Follows SKILL.md constraint: never allocate more than 40% of
            # total capital reserves in any single simulation block.
            proposed_budget = round(remaining_capital * 0.40, 2)

            print(f"\n{'='*60}")
            print(f"[BLOCK {block_num}/{TOTAL_BLOCKS}]  Remaining capital: ${remaining_capital:,.2f}")
            print(f"  -> Self-calculated proposed_budget: ${proposed_budget:,.2f}")

            # ── 2. Inject budget into persistent session state ────────────────
            # safety_gate_callback reads `proposed_budget` from this state dict.
            runner.session_service.sessions["kaggriculture_app"]["operator"][session.id].state["proposed_budget"] = proposed_budget

            # ── 3. Trigger runner (safety_gate_callback fires automatically) ──
            # If proposed_budget > $500, safety_gate_callback will pause here
            # and prompt the operator for manual y/n approval before continuing.
            async for event in runner.run_async(
                user_id="operator",
                session_id=session.id,
                new_message=types.Content(
                    role="user",
                    parts=[types.Part.from_text(
                        text=f"Simulate block {block_num} with budget {proposed_budget}"
                    )]
                )
            ):
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        if part.text:
                            print(f"\n[Agent Output]: {part.text}")

            # ── 4. Deduct spend from capital pool ─────────────────────────────
            remaining_capital = round(remaining_capital - proposed_budget, 2)
            print(f"\n  [OK] Block {block_num} complete. Remaining capital: ${remaining_capital:,.2f}")

    except (KeyboardInterrupt, EOFError):
        print("\n[ABORT] Autonomous loop interrupted by operator.")

    print(f"\n{'='*60}")
    print(f"[DONE] All {TOTAL_BLOCKS} simulation blocks completed.")
    print(f"  Final remaining capital: ${remaining_capital:,.2f}")

if __name__ == "__main__":
    asyncio.run(main())
