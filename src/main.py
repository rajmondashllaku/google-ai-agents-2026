"""Command-line entry point for the Kaggriculture farm simulation."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from .simulator import FarmSimulator
from .tools import load_scenarios


def build_parser() -> argparse.ArgumentParser:
    scenarios = sorted(load_scenarios())
    parser = argparse.ArgumentParser(
        description="Run the offline Kaggriculture Risk-Aware Crop Planner simulation."
    )
    parser.add_argument(
        "--mode",
        choices=["deterministic", "adk"],
        default="deterministic",
        help="decision provider: local deterministic policy or Gemini via ADK",
    )
    parser.add_argument(
        "--scenario",
        choices=scenarios,
        default="normal_growth",
        help="scripted local scenario to run",
    )
    parser.add_argument(
        "--blocks",
        type=int,
        default=10,
        help="number of simulation blocks (default: 10)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="reproducibility label for this scripted run (default: 42)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="suppress the block trace",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    decision_agent = None
    if args.mode == "adk":
        from .adk_agent import AdkConfigurationError, AdkKaggricultureAgent

        try:
            decision_agent = AdkKaggricultureAgent.from_environment()
        except AdkConfigurationError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

    try:
        simulator = FarmSimulator(
            scenario=args.scenario,
            blocks=args.blocks,
            seed=args.seed,
            agent=decision_agent,
        )
        simulator.run(verbose=not args.quiet)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        if decision_agent is not None:
            decision_agent.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
