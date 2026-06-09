"""
Thesis generator.

Subscribes to signal.created and market.tick. When enough signals for an
instrument accumulate within a rolling window, calls the configured LLM
provider and emits thesis.created.

JSON is extracted with a regex fallback and one retry on parse failure —
works across Anthropic, OpenAI, and Ollama without requiring JSON mode.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import structlog

from core.bus.base import Bus, Subscription
from core.schemas.events import EventEnvelope, EventType
from core.schemas.signal import Thesis, ThesisStatus
from reasoning.llm.base import LLMProvider

from .prompt import build_thesis_messages
from .settings import ThesisSettings

logger = structlog.get_logger(__name__)

_JSON_RE = re.compile(r"\{[\s\S]*\}", re.MULTILINE)


def _extract_json(text: str) -> dict[str, Any] | None:
    cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", text).strip()
    match = _JSON_RE.search(cleaned)
    if not match:
        return None
    try:
        result = json.loads(match.group())
        return result if isinstance(result, dict) else None
    except json.JSONDecodeError:
        return None


class ThesisGenerator:
    def __init__(
        self,
        bus: Bus,
        provider: LLMProvider,
        settings: ThesisSettings | None = None,
    ) -> None:
        self._bus = bus
        self._provider = provider
        self._settings = settings or ThesisSettings()
        self._signal_sub: Subscription | None = None
        self._tick_sub: Subscription | None = None

        # instrument → rolling buffer of (received_at, signal_payload)
        self._buffers: dict[str, deque[tuple[datetime, dict[str, Any]]]] = defaultdict(deque)
        self._cooldowns: dict[str, datetime] = {}
        self._last_prices: dict[str, str] = {}

    async def start(self) -> None:
        self._signal_sub = await self._bus.subscribe(EventType.SIGNAL_CREATED, self._handle_signal)
        self._tick_sub = await self._bus.subscribe(EventType.MARKET_TICK, self._handle_tick)
        logger.info("thesis_generator.started")

    async def stop(self) -> None:
        for sub in (self._signal_sub, self._tick_sub):
            if sub is not None:
                await self._bus.unsubscribe(sub)
        self._signal_sub = None
        self._tick_sub = None
        logger.info("thesis_generator.stopped")

    # ------------------------------------------------------------------
    # Bus handlers
    # ------------------------------------------------------------------

    async def _handle_tick(self, envelope: EventEnvelope) -> None:
        p = envelope.payload
        instrument: str = p.get("instrument", "")
        price: str = p.get("price", "")
        if instrument and price:
            self._last_prices[instrument] = price

    async def _handle_signal(self, envelope: EventEnvelope) -> None:
        payload = envelope.payload
        instruments: list[str] = payload.get("instruments", [])
        now = envelope.ingest_time

        for instrument in instruments:
            buf = self._buffers[instrument]
            buf.append((now, payload))

            cutoff = now - timedelta(minutes=self._settings.signal_window_minutes)
            while buf and buf[0][0] < cutoff:
                buf.popleft()

            if len(buf) >= self._settings.min_signals_to_trigger:
                if self._cooldown_ok(instrument, now):
                    await self._generate(instrument, list(buf), now)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _cooldown_ok(self, instrument: str, now: datetime) -> bool:
        last = self._cooldowns.get(instrument)
        if last is None or (now - last) >= timedelta(minutes=self._settings.cooldown_minutes):
            self._cooldowns[instrument] = now
            return True
        return False

    async def _generate(
        self,
        instrument: str,
        buffered: list[tuple[datetime, dict[str, Any]]],
        now: datetime,
    ) -> None:
        signals = [s for _, s in buffered[-self._settings.max_signals_per_prompt:]]
        signal_ids: list[UUID] = []
        for s in signals:
            raw_id = s.get("id")
            if raw_id:
                try:
                    signal_ids.append(UUID(str(raw_id)))
                except ValueError:
                    pass

        messages = build_thesis_messages(
            instrument, signals, self._last_prices.get(instrument)
        )

        logger.info("thesis_generator.generating", instrument=instrument, signals=len(signals))

        raw = await self._provider.complete(messages, max_tokens=self._settings.max_tokens)
        data = _extract_json(raw)

        if data is None:
            # One retry — ask the model to correct itself
            retry_messages = list(messages) + [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": "Invalid JSON. Reply with only the JSON object, no other text."},
            ]
            raw2 = await self._provider.complete(retry_messages, max_tokens=self._settings.max_tokens)  # type: ignore[arg-type]
            data = _extract_json(raw2)

        if data is None:
            logger.warning("thesis_generator.parse_failed", instrument=instrument)
            return

        thesis = Thesis(
            created_at=now,
            updated_at=now,
            instrument=str(data.get("instrument", instrument)),
            summary=str(data.get("summary", "")),
            body=str(data.get("body", "")),
            status=ThesisStatus.ACTIVE,
            invalidation_conditions=[str(c) for c in data.get("invalidation_conditions", [])],
            supporting_signal_ids=signal_ids,
        )

        ingest = datetime.now(UTC)
        await self._bus.publish(EventEnvelope(
            event_type=EventType.THESIS_CREATED,
            source="thesis_generator",
            event_time=now,
            ingest_time=ingest,
            payload={
                **thesis.model_dump(mode="json"),
                "direction": str(data.get("direction", "neutral")),
                "confidence": float(data.get("confidence", 0.0)),
                "time_horizon_hours": int(data.get("time_horizon_hours", self._settings.expiry_hours)),
            },
        ))
        logger.info("thesis_generator.emitted", instrument=instrument, summary=thesis.summary)
