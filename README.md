# Kaggriculture Risk-Aware Crop Planner

Kaggriculture Risk-Aware Crop Planner is a small, fully local farm simulation. At
each block it observes scripted weather, soil, and crop prices; selects one
candidate action with a deterministic baseline policy; validates that action
with independent Python guardrails; applies only approved actions; and records
the complete decision trace. It is a simulation, not a connection to a live
Kaggriculture service.

## Problem statement

Farm decisions interact: cash spent on seeds or irrigation is unavailable later,
planting depends on soil conditions, harvest timing depends on crop maturity, and
a sudden market move can make an otherwise reasonable trade unsafe. This project
demonstrates how a small planning agent can respond to changing observations
while hard safety rules remain outside the policy.

## Architecture

```text
data/sample_scenarios.json
            |
            v
  Simulator observes block
  (weather, soil, prices)
            |
            v
  KaggricultureAgent -> BaselinePolicy
            |              |
            |       candidate decision
            v              v
     validate_decision(state, decision)
       deterministic Python guardrails
            |
       +----+----+
       |         |
   approved   rejected/paused
       |         |
       v         v
  update state   apply WAIT
       +----+----+
            |
            v
  decision history, event log, console trace
```

The policy proposes actions in `src/policy.py`. It cannot mutate state.
`src/guardrails.py` independently checks money, volatility, inventory, soil,
irrigation usefulness, and maturity before `src/simulator.py` may apply an
action.

## State and action space

The typed `FarmState` persists for the duration of a run and tracks block number,
cash, wheat/corn seed inventory, harvested inventory, planted crop lots and
planting blocks, soil moisture and nutrients, weather, current and previous
prices, decision history, and event logs.

| Action | Main effect |
|---|---|
| `WAIT` | Preserve farm resources for the block |
| `BUY_SEEDS` | Spend cash and add seed inventory |
| `PLANT` | Consume seeds and create a planted crop lot |
| `IRRIGATE` | Spend cash and increase current soil moisture |
| `HARVEST` | Convert mature planted units into crop inventory |
| `SELL` | Convert crop inventory into cash at the current price |

Every decision contains an action, applicable crop and quantity, estimated cost,
a concise reason, and optional metadata such as confidence.

The two crop definitions are explicit and inspectable:

| Crop | Seed cost | Maturity | Yield per seed unit | Water need | Nutrient need |
|---|---:|---:|---:|---:|---:|
| Wheat | $40 | 2 blocks | 6 units | 0.50 | 0.50 |
| Corn | $30 | 3 blocks | 5 units | 0.42 | 0.55 |

## Deterministic safety guarantees

- A transaction may spend at most 40% of cash available when it is evaluated.
  Exactly 40% is allowed. The threshold is an upper bound, not a target.
- If a relevant crop's absolute block-to-block price change is greater than
  15%, all `BUY_SEEDS`, `PLANT`, and `SELL` actions for that crop are paused.
  Exactly 15% is allowed.
- Planting cannot exceed seed inventory and also requires adequate moisture and
  nutrients.
- Harvesting cannot exceed mature planted quantity.
- Selling cannot exceed harvested inventory.
- Irrigation is rejected when soil is already wet or substantial rain is
  forecast.
- The estimated cost is checked against a deterministic cost calculation; a
  policy cannot understate an expense.
- Rejected and paused candidates are converted to `WAIT` without changing farm
  resources.

## Local scenarios

Scenario observations live in `data/sample_scenarios.json` and vary each block.
The ten scripted blocks repeat if a longer run is requested.

- `normal_growth`: balanced moisture, gradual prices, and ordinary crop cycles.
- `drought`: low rain and moisture cause the policy to irrigate before planting
  or while a crop grows.
- `market_spike`: wheat rises 20% in block 5. The policy waits, the guardrail
  records a volatility pause, and selling resumes only after the movement
  settles.

The scenarios are fully scripted, so runs are reproducible. `--seed` is recorded
with the run for experiment labeling; scripted observations do not currently use
random sampling.

## Installation

Python 3.10 or newer is recommended.

```bash
python -m venv .venv
```

Activate the environment, then install the runtime and test dependencies:

```bash
pip install -r requirements.txt
```

The command-line simulator uses the Python standard library. Streamlit and
pandas provide the optional web dashboard.

## Run the simulation

Default ten-block run:

```bash
python -m src.main --scenario normal_growth --blocks 10
```

Run each configured scenario:

```bash
python -m src.main --scenario normal_growth --blocks 10
python -m src.main --scenario drought --blocks 10
python -m src.main --scenario market_spike --blocks 10
```

Use `--quiet` when only the exit status matters, or `--seed 123` to label a
reproducibility run.

## Run the Streamlit dashboard

Launch the interactive dashboard from the project root:

```bash
streamlit run streamlit_app.py
```

The app opens in a browser and provides scenario, block, starting-cash, and seed
controls. It displays final safety metrics, cash and market charts, weather and
soil trends, a block-by-block inspector, the full decision ledger, and final farm
inventory. The dashboard calls the same `FarmSimulator` and deterministic
guardrails as the command-line interface.

## Tests

```bash
pytest -q
```

The suite covers the 40% boundary and overspend rejection, the 15% volatility
boundary and above-threshold pause, seed inventory, maturity, sale accounting,
weather/soil-dependent policy choices, the complete market-spike safety outcome,
and repeatability.

## Representative console trace

This abridged example combines normal simulator output with the explicit
overspend fixture used by the guardrail tests:

```text
Block 1
Candidate: BUY_SEEDS wheat x4, estimated cost $160.00
Guardrails: APPROVED -- Expense $160.00 is within the 40% spending limit of $400.00.
Result: bought 4 wheat seed units; cash $840.00.

Overspend guardrail example
Candidate: BUY_SEEDS wheat x11, estimated cost $440.00
Guardrails: REJECTED -- Expense $440.00 exceeds the 40% spending limit of $400.00.
Result: WAIT; candidate not applied; cash unchanged at $1000.00.

Block 5 (market_spike)
Market: wheat +20.0%, corn +1.1%
Candidate: WAIT wheat, estimated cost $0.00
Guardrails: PAUSED -- wheat price changed 20.0%, exceeding the 15.0% volatility threshold; buy, plant, and sell actions are paused for this crop.
Result: WAIT; candidate not applied; cash unchanged at $840.00.
```

## Evaluation metrics

Each run reports starting/final cash, harvest inventory, planted quantity,
approved decisions, ordinary rejections, volatility pauses, and unsafe
transactions. The detailed `decision_history` and `event_logs` retained in state
support additional evaluation. The automated suite currently treats
`unsafe_transactions == 0`, exact boundary behavior, correct resource
accounting, observation-sensitive actions, and deterministic replay as its core
success criteria.

## Limitations

- Weather, soil, and prices are local scripted observations rather than live
  forecasts or exchange data.
- State persists across simulation blocks but is not saved across process
  restarts.
- The model represents one aggregate field, two crops, fixed yields, and simple
  moisture effects; it does not model pests, crop disease, fertilizer actions,
  land limits, or long-term soil depletion.
- The baseline policy is deliberately conservative and rule-based. Passing a
  guardrail means an action is safe under these rules, not economically optimal.

## Google ADK + Gemini Mode

The local simulator and deterministic safety layer remain the application core.
In optional ADK mode, a real Google ADK `Agent`, `Runner`, and in-memory session
let Gemini inspect the active block through read-only farm, weather, soil,
market, inventory, crop, and action tools. Gemini proposes one structured
`Decision`; it cannot mutate state. The existing Python guardrails still approve,
reject, or pause every proposal before the simulator applies it.

Copy `.env.example` to a local `.env` (which is ignored by Git) and configure:

```bash
GOOGLE_API_KEY=your_google_ai_studio_key
GEMINI_MODEL=gemini-2.5-flash
```

Run the reproducible offline policy, which uses no API credentials or tokens:

```bash
python -m src.main --mode deterministic --scenario normal_growth --blocks 10
```

Run Gemini through Google ADK:

```bash
python -m src.main --mode adk --scenario normal_growth --blocks 10
```

ADK mode requires a valid API key and may consume Gemini quota or billable
tokens. If Gemini is unavailable or returns malformed data, the adapter proposes
a safe `WAIT` and logs the fallback. Deterministic mode is recommended for tests
and reproducible evaluation. The optional `list_models.py` helper can list model
names for configured credentials; it is not part of either simulation path.

If Google returns `403 PERMISSION_DENIED`, verify the key and its project in
Google AI Studio. ADK mode uses the Gemini Developer API rather than Vertex AI,
and fatal authentication or project-access errors stop further model calls for
the remainder of that run while the simulator safely waits.
