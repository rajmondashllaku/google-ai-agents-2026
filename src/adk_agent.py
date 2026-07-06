"""Google ADK adapter that proposes decisions without mutating farm state."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from math import isfinite
from typing import Any
from uuid import uuid4

from dotenv import load_dotenv

from .guardrails import IRRIGATION_UNIT_COST, MAX_SPEND_FRACTION
from .models import ActionType, CROP_CATALOG, Decision, FarmState

APP_NAME = "kaggriculture_adk"
AGENT_NAME = "kaggriculture_risk_aware_planner"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
USER_ID = "local_farmer"

AGENT_INSTRUCTION = """
You are a risk-aware Kaggriculture farm planner.

Inspect the current farm state, weather, soil, crop status, inventory, and
market data using the available read-only tools. Recommend exactly one action
for the current simulation block.

You may recommend only: WAIT, BUY_SEEDS, PLANT, IRRIGATE, HARVEST, or SELL.
Prioritize crop viability, cash preservation, and risk management.

Do not recommend spending more than 40% of available cash.
Avoid buying, planting, or selling a crop whose absolute price movement is
greater than 15% since the previous block.
Do not recommend actions that violate seed inventory, harvested inventory,
soil requirements, or crop maturity constraints.

Return only one JSON object with exactly these fields:
{
  "action": "WAIT",
  "crop": null,
  "quantity": null,
  "estimated_cost": 0.0,
  "reason": "Concise explanation"
}

BUY_SEEDS costs quantity times the crop seed cost. IRRIGATE costs $20 per unit.
Seeds are prepaid, so PLANT costs $0. HARVEST, SELL, and WAIT also have an
estimated cost of $0. Do not wrap the JSON in Markdown.

Your recommendation is only a proposal. The application independently applies
deterministic Python guardrails before any state change.
""".strip()

logger = logging.getLogger(__name__)

ResponseProvider = Callable[[FarmState], str]


class AdkConfigurationError(RuntimeError):
    """Raised when ADK mode is missing required local configuration."""


class AdkDecisionParseError(ValueError):
    """Raised when a Gemini response is not a strict application decision."""


class AdkUnavailableError(RuntimeError):
    """Represents a safely summarized Gemini service or authorization failure."""


def _safe_model_error_message(error: Exception) -> str:
    code = getattr(error, "code", None)
    if code == 401:
        return (
            "Gemini authentication failed (HTTP 401). Check GOOGLE_API_KEY "
            "and create a new key if necessary."
        )
    if code == 403:
        return (
            "Gemini access was denied (HTTP 403). The API key's Google project "
            "is not permitted to use Gemini; use a key from an enabled project "
            "or contact Google support."
        )
    if code == 404:
        return (
            "The configured Gemini model was not found (HTTP 404). "
            "Check GEMINI_MODEL and model access."
        )
    if code == 429:
        return (
            "Gemini quota or rate limits were reached (HTTP 429). "
            "Wait before retrying or check project quota."
        )
    if isinstance(code, int):
        return f"Gemini request failed with HTTP {code}."
    return f"Gemini request failed ({type(error).__name__})."


def _is_fatal_model_error(error: Exception) -> bool:
    return getattr(error, "code", None) in {400, 401, 403, 404}


class ActiveFarmState:
    """Temporarily exposes the current block state to read-only tool closures."""

    def __init__(self) -> None:
        self._state: FarmState | None = None

    @contextmanager
    def bind(self, state: FarmState) -> Iterator[None]:
        if self._state is not None:
            raise RuntimeError("Farm state is already bound to an ADK turn")
        self._state = state
        try:
            yield
        finally:
            self._state = None

    def get(self) -> FarmState:
        if self._state is None:
            raise RuntimeError("No active farm state is bound")
        return self._state


def create_read_only_tools(binding: ActiveFarmState) -> list[Callable[..., dict]]:
    """Create ADK-compatible tools backed by the currently bound FarmState."""

    def get_farm_state() -> dict:
        """Return the current block, cash, spending limit, and field summary."""
        state = binding.get()
        return {
            "block_number": state.block_number,
            "cash": round(state.cash, 2),
            "maximum_action_spend": round(
                state.cash * MAX_SPEND_FRACTION,
                2,
            ),
            "soil_moisture": state.soil_moisture,
            "soil_nutrients": state.soil_nutrients,
            "planted_seed_units": sum(
                planted.quantity for planted in state.planted_crops
            ),
        }

    def get_weather() -> dict:
        """Return the current weather forecast for this simulation block."""
        weather = binding.get().weather
        return {
            "summary": weather.summary,
            "rain_probability": weather.rain_probability,
            "temperature_c": weather.temperature_c,
        }

    def get_soil() -> dict:
        """Return current soil moisture and nutrient measurements."""
        state = binding.get()
        return {
            "moisture": state.soil_moisture,
            "nutrients": state.soil_nutrients,
        }

    def get_market_prices() -> dict:
        """Return current, previous, and percentage price changes by crop."""
        state = binding.get()
        return {
            crop: {
                "current_price": state.current_market_prices[crop],
                "previous_price": state.previous_market_prices[crop],
                "change_percent": round(state.market_change(crop) * 100, 2),
            }
            for crop in CROP_CATALOG
        }

    def get_inventory() -> dict:
        """Return available seed and harvested crop inventory."""
        state = binding.get()
        return {
            "seeds": dict(state.seed_inventory),
            "harvested_crops": dict(state.inventory),
        }

    def get_planted_crops() -> dict:
        """Return planted crop lots with age and maturity information."""
        state = binding.get()
        return {
            "planted_crops": [
                {
                    "crop": planted.crop,
                    "quantity": planted.quantity,
                    "planted_block": planted.planted_block,
                    "age_blocks": planted.age(state.block_number),
                    "is_mature": planted.is_mature(state.block_number),
                }
                for planted in state.planted_crops
            ]
        }

    def get_available_actions() -> dict:
        """Return the supported action names, crops, and deterministic costs."""
        return {
            "actions": [action.value for action in ActionType],
            "crops": {
                name: {
                    "seed_cost": crop.seed_cost,
                    "blocks_to_maturity": crop.blocks_to_maturity,
                    "yield_per_seed": crop.yield_per_seed,
                    "water_need": crop.water_need,
                    "nutrient_need": crop.nutrient_need,
                }
                for name, crop in CROP_CATALOG.items()
            },
            "irrigation_unit_cost": IRRIGATION_UNIT_COST,
            "cost_rules": {
                "BUY_SEEDS": "quantity multiplied by seed_cost",
                "IRRIGATE": "quantity multiplied by irrigation_unit_cost",
                "WAIT": 0,
                "PLANT": 0,
                "HARVEST": 0,
                "SELL": 0,
            },
        }

    return [
        get_farm_state,
        get_weather,
        get_soil,
        get_market_prices,
        get_inventory,
        get_planted_crops,
        get_available_actions,
    ]


def parse_adk_decision(response_text: str) -> Decision:
    """Strictly convert a Gemini JSON response into the existing Decision model."""
    try:
        payload = json.loads(response_text.strip())
    except (json.JSONDecodeError, TypeError) as exc:
        raise AdkDecisionParseError("Response is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise AdkDecisionParseError("Response must be one JSON object")

    required = {"action", "crop", "quantity", "estimated_cost", "reason"}
    allowed = required | {"metadata"}
    if set(payload) != required and not (
        required.issubset(payload) and set(payload).issubset(allowed)
    ):
        raise AdkDecisionParseError(
            "Response fields do not match the decision schema"
        )

    action_value = payload["action"]
    if not isinstance(action_value, str):
        raise AdkDecisionParseError("action must be a string")
    try:
        action = ActionType(action_value.strip().upper())
    except ValueError as exc:
        raise AdkDecisionParseError("action is not supported") from exc

    crop_value = payload["crop"]
    if crop_value is not None and not isinstance(crop_value, str):
        raise AdkDecisionParseError("crop must be a string or null")
    crop = crop_value.strip().lower() if isinstance(crop_value, str) else None
    if crop is not None and crop not in CROP_CATALOG:
        raise AdkDecisionParseError("crop is not supported")
    if action in {
        ActionType.BUY_SEEDS,
        ActionType.PLANT,
        ActionType.HARVEST,
        ActionType.SELL,
    } and crop is None:
        raise AdkDecisionParseError(f"{action.value} requires a crop")

    quantity = payload["quantity"]
    if action is ActionType.WAIT:
        if quantity is not None:
            raise AdkDecisionParseError("WAIT quantity must be null")
    elif (
        not isinstance(quantity, int)
        or isinstance(quantity, bool)
        or quantity <= 0
    ):
        raise AdkDecisionParseError("quantity must be a positive integer")

    cost_value = payload["estimated_cost"]
    if (
        not isinstance(cost_value, (int, float))
        or isinstance(cost_value, bool)
        or cost_value < 0
    ):
        raise AdkDecisionParseError("estimated_cost must be non-negative")
    estimated_cost = float(cost_value)
    if not isfinite(estimated_cost):
        raise AdkDecisionParseError("estimated_cost must be finite")
    if action is ActionType.WAIT and estimated_cost != 0.0:
        raise AdkDecisionParseError("WAIT estimated_cost must be zero")

    reason = payload["reason"]
    if not isinstance(reason, str) or not reason.strip():
        raise AdkDecisionParseError("reason must be a non-empty string")

    metadata_value = payload.get("metadata", {})
    if not isinstance(metadata_value, dict):
        raise AdkDecisionParseError("metadata must be an object when provided")
    metadata = dict(metadata_value)
    metadata["source"] = "google_adk_gemini"

    return Decision(
        action=action,
        crop=crop,
        quantity=quantity,
        estimated_cost=estimated_cost,
        reason=reason.strip(),
        metadata=metadata,
    )


def fallback_wait(
    error: Exception,
    *,
    log_warning: bool = True,
) -> Decision:
    """Create a safe fallback without exposing exception details or secrets."""
    error_type = type(error).__name__
    if isinstance(error, AdkUnavailableError):
        safe_reason = str(error)
    else:
        safe_reason = (
            "Gemini response was invalid or unavailable "
            f"({error_type})."
        )
    if log_warning:
        logger.warning("ADK decision fallback: %s", safe_reason)
    return Decision(
        action=ActionType.WAIT,
        crop=None,
        quantity=None,
        estimated_cost=0.0,
        reason=f"Fallback: {safe_reason}",
        metadata={"source": "google_adk_fallback", "error_type": error_type},
    )


class AdkKaggricultureAgent:
    """Uses a persistent ADK session to propose one Decision per farm block."""

    def __init__(
        self,
        *,
        model: str,
        response_provider: ResponseProvider | None = None,
    ) -> None:
        self.model = model
        self._response_provider = response_provider
        self._state_binding = ActiveFarmState()
        self._tools = create_read_only_tools(self._state_binding)
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._session_service: Any | None = None
        self._runner: Any | None = None
        self.root_agent: Any | None = None
        self._session_id = f"farm-{uuid4().hex}"
        self._last_model_error_message: str | None = None
        self._circuit_message: str | None = None

    @classmethod
    def from_environment(cls) -> "AdkKaggricultureAgent":
        load_dotenv(override=False)
        api_key = os.getenv("GOOGLE_API_KEY", "").strip()
        if not api_key:
            raise AdkConfigurationError(
                "ADK mode requires GOOGLE_API_KEY. Set it in the environment "
                "or a local .env file; deterministic mode needs no key."
            )
        model = os.getenv("GEMINI_MODEL", "").strip() or DEFAULT_GEMINI_MODEL
        os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "FALSE"
        return cls(model=model)

    def _initialize_runtime(self) -> None:
        if self._runner is not None:
            return
        from google.adk.agents import Agent
        from google.adk.runners import Runner
        from google.adk.sessions import InMemorySessionService
        from google.genai import types

        self.root_agent = Agent(
            name=AGENT_NAME,
            description="Proposes one risk-aware action for the local farm simulation.",
            model=self.model,
            instruction=AGENT_INSTRUCTION,
            tools=self._tools,
            generate_content_config=types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=512,
            ),
            on_model_error_callback=self._handle_model_error,
        )
        self._session_service = InMemorySessionService()
        self._runner = Runner(
            agent=self.root_agent,
            app_name=APP_NAME,
            session_service=self._session_service,
        )
        self._event_loop = asyncio.new_event_loop()
        self._event_loop.run_until_complete(
            self._session_service.create_session(
                app_name=APP_NAME,
                user_id=USER_ID,
                session_id=self._session_id,
            )
        )

    def _handle_model_error(
        self,
        callback_context: Any,
        llm_request: Any,
        error: Exception,
    ) -> Any:
        """Convert ADK model failures into controlled responses without tracebacks."""
        del callback_context, llm_request
        from google.adk.models.llm_response import LlmResponse
        from google.genai import types

        safe_message = _safe_model_error_message(error)
        self._last_model_error_message = safe_message
        if _is_fatal_model_error(error):
            self._circuit_message = safe_message
        response_text = json.dumps(
            {
                "action": "WAIT",
                "crop": None,
                "quantity": None,
                "estimated_cost": 0.0,
                "reason": f"Fallback: {safe_message}",
            }
        )
        return LlmResponse(
            content=types.Content(
                role="model",
                parts=[types.Part.from_text(text=response_text)],
            )
        )

    async def _run_adk_turn(self, block_number: int) -> str:
        from google.genai import types

        assert self._runner is not None
        self._last_model_error_message = None
        prompt = (
            f"Simulation block {block_number}. Inspect the live farm state with "
            "the read-only tools, then propose exactly one decision as strict JSON."
        )
        message = types.Content(
            role="user",
            parts=[types.Part.from_text(text=prompt)],
        )
        final_text: str | None = None
        async for event in self._runner.run_async(
            user_id=USER_ID,
            session_id=self._session_id,
            new_message=message,
        ):
            if not event.is_final_response() or event.content is None:
                continue
            text_parts = [
                part.text
                for part in (event.content.parts or [])
                if getattr(part, "text", None)
            ]
            if text_parts:
                final_text = "".join(text_parts)
        if self._last_model_error_message is not None:
            raise AdkUnavailableError(self._last_model_error_message)
        if final_text is None:
            raise AdkDecisionParseError("ADK returned no final text response")
        return final_text

    def choose_action(self, state: FarmState) -> Decision:
        if self._circuit_message is not None:
            return fallback_wait(
                AdkUnavailableError(self._circuit_message),
                log_warning=False,
            )
        with self._state_binding.bind(state):
            try:
                if self._response_provider is not None:
                    response_text = self._response_provider(state)
                else:
                    self._initialize_runtime()
                    assert self._event_loop is not None
                    response_text = self._event_loop.run_until_complete(
                        self._run_adk_turn(state.block_number)
                    )
                return parse_adk_decision(response_text)
            except Exception as exc:
                return fallback_wait(exc)

    def close(self) -> None:
        if self._event_loop is None:
            return
        try:
            if self._runner is not None:
                self._event_loop.run_until_complete(self._runner.close())
        except Exception as exc:
            logger.warning("ADK runner close failed (%s)", type(exc).__name__)
        finally:
            self._event_loop.close()
            self._event_loop = None
            self._runner = None
