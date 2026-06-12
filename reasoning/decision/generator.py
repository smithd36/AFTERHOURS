"""
Decision generator.

Subscribes to thesis.created. For each new active thesis, calls the LLM to
produce a specific trade proposal and emits decision.proposed.

Separation of duties (PLANNING §4.5):
  LLM contributes: side, time_horizon, reasoning, evidence, confidence.
  Deterministic code provides: size_usd (via risk engine), prompt_hash, ModelInfo.
  The LLM never sets size_usd.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import structlog
from pydantic import ValidationError

from core.bus.base import Bus, Subscription
from core.schemas.decision import (
    Decision,
    DecisionStatus,
    Evidence,
    ModelInfo,
    OrderType,
    Proposal,
)
from core.schemas.events import EventEnvelope, EventType
from reasoning.llm.base import LLMProvider
from reasoning.llm.settings import LLMSettings
from reasoning.thesis.generator import _extract_json

from .prompt import build_decision_messages
from .settings import DecisionSettings

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from watchlist.manager import WatchlistManager

logger = structlog.get_logger(__name__)


def _as_uuid(raw: object) -> UUID | None:
    """Parse a thesis/id field into a UUID, or None if absent/malformed."""
    if not raw:
        return None
    try:
        return UUID(str(raw))
    except ValueError:
        return None


class DecisionGenerator:
    def __init__(
        self,
        bus: Bus,
        provider: LLMProvider,
        llm_settings: LLMSettings | None = None,
        settings: DecisionSettings | None = None,
        watchlist: WatchlistManager | None = None,
    ) -> None:
        self._bus = bus
        self._provider = provider
        self._llm_settings = llm_settings or LLMSettings()
        self._settings = settings or DecisionSettings()
        self._watchlist = watchlist
        self._thesis_sub: Subscription | None = None
        self._tick_sub: Subscription | None = None

        self._processed_thesis_ids: set[str] = set()
        self._prices: dict[str, Decimal] = {}

    async def start(self) -> None:
        self._thesis_sub = await self._bus.subscribe(EventType.THESIS_CREATED, self._handle_thesis)
        self._tick_sub = await self._bus.subscribe(EventType.MARKET_TICK, self._handle_tick)
        logger.info("decision_generator.started")

    async def stop(self) -> None:
        for sub in (self._thesis_sub, self._tick_sub):
            if sub is not None:
                await self._bus.unsubscribe(sub)
        self._thesis_sub = None
        self._tick_sub = None
        logger.info("decision_generator.stopped")

    # ------------------------------------------------------------------

    async def _handle_tick(self, envelope: EventEnvelope) -> None:
        p = envelope.payload
        instrument: str = p.get("instrument", "")
        price: str = p.get("price", "")
        if instrument and price:
            self._prices[instrument] = Decimal(price)

    async def _handle_thesis(self, envelope: EventEnvelope) -> None:
        p = envelope.payload
        thesis_id: str = str(p.get("id", ""))
        instrument: str = str(p.get("instrument", ""))
        status: str = str(p.get("status", ""))

        if not thesis_id or not instrument:
            return
        if status not in ("active", ""):
            return
        if thesis_id in self._processed_thesis_ids:
            return
        if self._watchlist is not None and instrument not in self._watchlist.active_instruments:
            return
        self._processed_thesis_ids.add(thesis_id)

        # event_time, not ingest_time: the decision's financial clock must be
        # the thesis's event clock or replay produces wall-clock decisions
        # (two-clock rule, PLANNING §4.6). Live, the two differ by milliseconds.
        await self._generate(p, envelope.event_time)

    async def _generate(self, thesis: dict[str, Any], now: datetime) -> None:
        instrument: str = str(thesis.get("instrument", ""))
        signal_ids: list[UUID] = []
        for raw in thesis.get("supporting_signal_ids", []):
            try:
                signal_ids.append(UUID(str(raw)))
            except ValueError:
                pass

        current_price = self._prices.get(instrument)

        messages = build_decision_messages(
            instrument=instrument,
            thesis_summary=str(thesis.get("summary", "")),
            thesis_body=str(thesis.get("body", "")),
            thesis_direction=str(thesis.get("direction", "neutral")),
            thesis_confidence=float(thesis.get("confidence", 0.0)),
            signal_ids=signal_ids,
            current_price=current_price,
            size_usd=Decimal("0"),  # placeholder; risk engine fills this in
        )

        prompt_text = json.dumps(messages, ensure_ascii=False)
        prompt_hash = hashlib.sha256(prompt_text.encode()).hexdigest()

        logger.info("decision_generator.generating", instrument=instrument)

        raw = await self._provider.complete(messages, max_tokens=self._settings.max_tokens)
        data = _extract_json(raw)

        if data is None:
            retry = list(messages) + [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": "Invalid JSON. Reply with only the JSON object."},
            ]
            raw2 = await self._provider.complete(retry, max_tokens=self._settings.max_tokens)  # type: ignore[arg-type]
            data = _extract_json(raw2)

        if data is None:
            logger.warning("decision_generator.parse_failed", instrument=instrument)
            return

        model = self._llm_settings.model or "unknown"

        # Build the evidence list defensively: drop any item that doesn't cite a
        # parseable signal id or carries an out-of-vocabulary stance. An empty
        # result is rejected below by the schema (no evidence → no trade, §6.2).
        evidence: list[Evidence] = []
        for e in data.get("evidence", []):
            raw_id = e.get("signal_id")
            if not raw_id:
                continue
            try:
                evidence.append(
                    Evidence(
                        signal_id=UUID(str(raw_id)),
                        summary=str(e.get("summary", "")),
                        stance=str(e.get("stance", "supporting")).strip().lower(),
                    )
                )
            except (ValueError, ValidationError):
                continue

        # Validate the assembled decision against the schema BEFORE publishing
        # (PLANNING §4.5: "schema-validated, range-checked"). The LLM-supplied
        # side, time_horizon, confidence and evidence are untrusted: an
        # out-of-range confidence would corrupt the calibration buckets the
        # autonomy gates depend on, and an invalid side would propagate until
        # Side(...) raises inside the ledger's fill handler — after the fill is
        # already in the audit log (fill recorded, position never opened). A
        # model that emits garbage gets no trade rather than a corrupt one.
        try:
            decision = Decision(
                id=uuid4(),
                created_at=now,
                originating_thesis_id=_as_uuid(thesis.get("id")),
                input_signal_ids=signal_ids,
                model=ModelInfo(
                    provider=self._llm_settings.provider,
                    model_id=model,
                    prompt_hash=prompt_hash,
                    temperature=self._llm_settings.temperature,
                ),
                proposal=Proposal(
                    instrument=instrument,
                    side=str(data.get("side", "")).strip().lower() or None,
                    size_usd=Decimal("0"),  # risk engine fills this in
                    order_type=OrderType.MARKET,
                    time_horizon=str(data.get("time_horizon", "")).strip().lower() or None,
                ),
                reasoning=str(data.get("reasoning", "")),
                evidence=evidence,
                confidence=data.get("confidence"),
                status=DecisionStatus.PROPOSED,
            )
        except ValidationError as exc:
            logger.warning(
                "decision_generator.validation_failed",
                instrument=instrument,
                side=data.get("side"),
                confidence=data.get("confidence"),
                evidence_count=len(evidence),
                errors=exc.errors(include_url=False, include_input=False),
            )
            return

        ingest = datetime.now(UTC)
        await self._bus.publish(EventEnvelope(
            event_type=EventType.DECISION_PROPOSED,
            source="decision_generator",
            event_time=now,
            ingest_time=ingest,
            correlation_id=decision.id,
            payload=decision.model_dump(mode="json"),
        ))
        logger.info("decision_generator.emitted", instrument=instrument,
                    decision_id=str(decision.id))
