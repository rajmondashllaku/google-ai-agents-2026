"""Interactive dashboard for the Kaggriculture farm simulation."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from src.models import CROP_CATALOG, DecisionRecord, ValidationStatus
from src.simulator import FarmSimulator, SimulationResult
from src.tools import load_scenarios


SCENARIO_DESCRIPTIONS = {
    "normal_growth": "Balanced conditions with gradual market changes.",
    "drought": "Low rain and dry soil make irrigation decisions important.",
    "market_spike": "A 20% wheat price jump activates the volatility pause.",
}


def run_simulation(
    scenario: str,
    blocks: int,
    seed: int,
    initial_cash: float,
) -> SimulationResult:
    return FarmSimulator(
        scenario=scenario,
        blocks=blocks,
        seed=seed,
        initial_cash=initial_cash,
    ).run(verbose=False)


def decision_rows(result: SimulationResult) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record, snapshot in zip(
        result.state.decision_history,
        result.block_snapshots,
        strict=True,
    ):
        rows.append(
            {
                "Block": record.block_number,
                "Candidate": record.decision.action.value,
                "Crop": record.decision.crop or "—",
                "Quantity": record.decision.quantity or 0,
                "Est. cost": record.decision.estimated_cost,
                "Guardrail": record.validation.status.value,
                "Applied": record.applied_action.value,
                "Cash after": snapshot.cash,
                "Reason": record.decision.reason,
                "Validation": record.validation.reason,
                "Result": record.result,
            }
        )
    return rows


def _render_sidebar() -> tuple[str, int, int, float, bool]:
    scenarios = sorted(load_scenarios())
    with st.sidebar:
        st.header("Simulation controls")
        st.caption("Configure a deterministic local run.")
        with st.form("simulation_controls"):
            scenario = st.selectbox(
                "Scenario",
                options=scenarios,
                index=scenarios.index("normal_growth"),
                format_func=lambda name: name.replace("_", " ").title(),
                key="scenario",
            )
            st.caption(SCENARIO_DESCRIPTIONS.get(scenario, "Local scenario."))
            blocks = int(
                st.number_input(
                    "Blocks",
                    min_value=1,
                    max_value=50,
                    value=10,
                    step=1,
                    key="blocks",
                )
            )
            initial_cash = float(
                st.number_input(
                    "Starting cash",
                    min_value=100.0,
                    max_value=100_000.0,
                    value=1_000.0,
                    step=100.0,
                    format="%.2f",
                    key="initial_cash",
                )
            )
            seed = int(
                st.number_input(
                    "Seed label",
                    min_value=0,
                    max_value=1_000_000,
                    value=42,
                    step=1,
                    key="seed",
                    help="Recorded for reproducibility; scenarios are scripted.",
                )
            )
            submitted = st.form_submit_button(
                "Run simulation",
                type="primary",
                width="stretch",
            )

        st.divider()
        st.subheader("Hard safety limits")
        st.markdown(
            "- Maximum **40% of current cash** per expense\n"
            "- Pause crop transactions above **15% price movement**\n"
            "- Enforce seed, inventory, soil, and maturity constraints"
        )
    return scenario, blocks, seed, initial_cash, submitted


def _render_metrics(result: SimulationResult) -> None:
    state = result.state
    cash_delta = state.cash - result.starting_cash
    harvested = sum(state.inventory.values())
    planted = sum(crop.quantity for crop in state.planted_crops)
    columns = st.columns(4)
    columns[0].metric(
        "Final cash",
        f"${state.cash:,.2f}",
        f"${cash_delta:+,.2f}",
        border=True,
    )
    columns[1].metric(
        "Harvest inventory",
        f"{harvested} units",
        border=True,
    )
    columns[2].metric(
        "Volatility pauses",
        result.volatility_pauses,
        border=True,
    )
    columns[3].metric(
        "Unsafe transactions",
        result.unsafe_transactions,
        border=True,
    )
    st.caption(
        f"Planted: {planted} seed units · Approved: "
        f"{result.approved_decisions} · Rejected: {result.rejected_decisions}"
    )


def _render_charts(result: SimulationResult) -> None:
    snapshots = result.block_snapshots
    cash = pd.DataFrame(
        {
            "Block": [snapshot.block_number for snapshot in snapshots],
            "Cash": [snapshot.cash for snapshot in snapshots],
        }
    ).set_index("Block")
    prices = pd.DataFrame(
        [
            {"Block": snapshot.block_number, **snapshot.market_prices}
            for snapshot in snapshots
        ]
    ).set_index("Block")
    conditions = pd.DataFrame(
        {
            "Block": [snapshot.block_number for snapshot in snapshots],
            "Soil moisture": [snapshot.soil_moisture for snapshot in snapshots],
            "Soil nutrients": [snapshot.soil_nutrients for snapshot in snapshots],
            "Rain probability": [
                snapshot.rain_probability for snapshot in snapshots
            ],
        }
    ).set_index("Block")

    left, right = st.columns(2)
    with left:
        st.subheader("Cash over time")
        st.line_chart(cash)
    with right:
        st.subheader("Crop prices")
        st.line_chart(prices)
    st.subheader("Weather and soil conditions")
    st.line_chart(conditions)


def _status_message(record: DecisionRecord) -> None:
    message = f"{record.validation.status.value}: {record.validation.reason}"
    if record.validation.status is ValidationStatus.APPROVED:
        st.success(message)
    elif record.validation.status is ValidationStatus.PAUSED:
        st.warning(message)
    else:
        st.error(message)


def _render_block_inspector(result: SimulationResult) -> None:
    st.subheader("Inspect one block")
    block_number = st.select_slider(
        "Block",
        options=list(range(1, result.blocks_run + 1)),
        value=result.blocks_run,
        key=(
            f"inspected_block_{result.scenario}_{result.blocks_run}_"
            f"{result.seed}_{result.starting_cash}"
        ),
    )
    record = result.state.decision_history[block_number - 1]
    snapshot = result.block_snapshots[block_number - 1]

    weather, soil, market = st.columns(3)
    weather.metric(
        "Weather",
        snapshot.weather_summary.title(),
        f"{snapshot.rain_probability * 100:.0f}% rain",
        delta_color="off",
    )
    soil.metric(
        "Soil moisture",
        f"{snapshot.soil_moisture:.2f}",
        f"Nutrients {snapshot.soil_nutrients:.2f}",
        delta_color="off",
    )
    market.metric(
        "Wheat price",
        f"${snapshot.market_prices['wheat']:.2f}",
        (
            f"{result.state.decision_history[block_number - 1].decision.crop or 'No'} "
            "crop focus"
        ),
        delta_color="off",
    )

    decision = record.decision
    quantity = f" × {decision.quantity}" if decision.quantity is not None else ""
    crop = f" {decision.crop}" if decision.crop else ""
    st.markdown(
        f"**Candidate:** `{decision.action.value}{crop}{quantity}`  \n"
        f"**Estimated cost:** `${decision.estimated_cost:,.2f}`  \n"
        f"**Policy reason:** {decision.reason}"
    )
    _status_message(record)
    st.info(f"Applied result: {record.result}")


def _render_decisions(result: SimulationResult) -> None:
    rows = decision_rows(result)
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        width="stretch",
        column_config={
            "Est. cost": st.column_config.NumberColumn(format="$%.2f"),
            "Cash after": st.column_config.NumberColumn(format="$%.2f"),
        },
    )
    pauses = [
        record
        for record in result.state.decision_history
        if record.validation.status is ValidationStatus.PAUSED
    ]
    rejections = [
        record
        for record in result.state.decision_history
        if record.validation.status is ValidationStatus.REJECTED
    ]
    if pauses:
        st.warning(
            f"{len(pauses)} volatility pause(s): "
            + ", ".join(f"block {record.block_number}" for record in pauses)
        )
    if rejections:
        st.error(
            f"{len(rejections)} rejected candidate(s): "
            + ", ".join(f"block {record.block_number}" for record in rejections)
        )


def _render_farm_state(result: SimulationResult) -> None:
    state = result.state
    inventory_rows = [
        {
            "Crop": crop.title(),
            "Seeds": state.seed_inventory[crop],
            "Harvested units": state.inventory[crop],
            "Current price": state.current_market_prices[crop],
        }
        for crop in CROP_CATALOG
    ]
    st.subheader("Final inventory")
    st.dataframe(
        pd.DataFrame(inventory_rows),
        hide_index=True,
        width="stretch",
        column_config={
            "Current price": st.column_config.NumberColumn(format="$%.2f"),
        },
    )

    st.subheader("Crop definitions")
    crop_rows = [
        {
            "Crop": crop.name.title(),
            "Seed cost": crop.seed_cost,
            "Maturity blocks": crop.blocks_to_maturity,
            "Yield per seed": crop.yield_per_seed,
            "Water need": crop.water_need,
            "Nutrient need": crop.nutrient_need,
        }
        for crop in CROP_CATALOG.values()
    ]
    st.dataframe(
        pd.DataFrame(crop_rows),
        hide_index=True,
        width="stretch",
        column_config={
            "Seed cost": st.column_config.NumberColumn(format="$%.2f"),
        },
    )

    if state.planted_crops:
        st.subheader("Active planted crops")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Crop": planted.crop.title(),
                        "Quantity": planted.quantity,
                        "Planted block": planted.planted_block,
                        "Age": planted.age(state.block_number),
                    }
                    for planted in state.planted_crops
                ]
            ),
            hide_index=True,
            width="stretch",
        )
    else:
        st.info("No crops remain planted at the end of this run.")


def _render_safety() -> None:
    st.subheader("Deterministic guardrail layer")
    st.markdown(
        """
The policy proposes one structured action, but it cannot update farm state.
`validate_decision` independently recalculates costs and validates:

1. **Spending:** expenses must be at or below 40% of current cash.
2. **Volatility:** buy, plant, and sell actions pause above a 15% crop-price move.
3. **Resources:** seeds and harvested inventory cannot go below zero.
4. **Maturity:** crops cannot be harvested before their maturity block.
5. **Field conditions:** planting and irrigation must have a meaningful effect.

Rejected or paused candidates become `WAIT`, and the simulator records the reason.
        """
    )


def main() -> None:
    st.set_page_config(
        page_title="Kaggriculture Crop Planner",
        page_icon="🌾",
        layout="wide",
    )
    st.title("🌾 Kaggriculture Risk-Aware Crop Planner")
    st.caption(
        "Offline simulation · deterministic policy · independent safety guardrails"
    )

    scenario, blocks, seed, initial_cash, submitted = _render_sidebar()
    if submitted or "simulation_result" not in st.session_state:
        st.session_state.simulation_result = run_simulation(
            scenario,
            blocks,
            seed,
            initial_cash,
        )

    result: SimulationResult = st.session_state.simulation_result
    st.markdown(
        f"### {result.scenario.replace('_', ' ').title()} "
        f"· {result.blocks_run} blocks"
    )
    if result.unsafe_transactions == 0:
        st.success("Run completed with zero unsafe transactions.")
    else:
        st.error(
            f"Safety failure: {result.unsafe_transactions} unsafe transaction(s)."
        )

    _render_metrics(result)
    overview, decisions, farm_state, safety = st.tabs(
        ["Overview", "Decision ledger", "Farm state", "Safety model"]
    )
    with overview:
        _render_charts(result)
        _render_block_inspector(result)
    with decisions:
        _render_decisions(result)
    with farm_state:
        _render_farm_state(result)
    with safety:
        _render_safety()


if __name__ == "__main__":
    main()
