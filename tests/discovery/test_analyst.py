"""AIAnalyst: parses JSON, retries once on bad JSON, gives up cleanly, and the
prompt forbids buy/sell calls (the LLM explains, it never decides)."""

from datetime import UTC, datetime

import pytest

from discovery.analyst import AIAnalyst, _build_messages
from discovery.score import Candidate, ScoredContribution
from reasoning.llm.base import Message

NOW = datetime(2026, 6, 16, tzinfo=UTC)

CANDIDATE = Candidate(
    instrument="AAA",
    score=0.62,
    factors=("insider_activity",),
    contributions=(
        ScoredContribution(
            factor="insider_activity",
            weighted=0.45,
            age_days=2.0,
            summary="CEO bought $2M of AAA",
            source="insider_tx",
        ),
    ),
)

GOOD = (
    '{"thesis": "insider buying", "risks": ["thin float"], '
    '"evidence_summary": "one buy", "suggested_step": "watch"}'
)


class FakeProvider:
    """Returns canned responses in order; records the messages it was sent."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.calls: list[list[Message]] = []

    async def complete(self, messages: list[Message], *, max_tokens: int = 1024) -> str:
        self.calls.append(messages)
        return self._responses.pop(0)


@pytest.mark.asyncio
async def test_parses_valid_json():
    analyst = AIAnalyst(FakeProvider([GOOD]))
    result = await analyst.analyze(CANDIDATE)
    assert result is not None
    assert result.instrument == "AAA"
    assert result.thesis == "insider buying"
    assert result.risks == ["thin float"]


@pytest.mark.asyncio
async def test_retries_once_on_bad_json():
    provider = FakeProvider(["not json", GOOD])
    result = await AIAnalyst(provider).analyze(CANDIDATE)
    assert result is not None
    assert len(provider.calls) == 2  # original + one retry


@pytest.mark.asyncio
async def test_gives_up_after_failed_retry():
    provider = FakeProvider(["nope", "still nope"])
    assert await AIAnalyst(provider).analyze(CANDIDATE) is None


def test_prompt_forbids_buy_sell_and_includes_evidence():
    messages = _build_messages(CANDIDATE)
    system = messages[0]["content"]
    user = messages[1]["content"]
    assert "DO NOT" in system  # no buy/sell calls
    assert "untrusted data" in system  # prompt-injection guard
    assert "CEO bought $2M of AAA" in user  # evidence is in the prompt
