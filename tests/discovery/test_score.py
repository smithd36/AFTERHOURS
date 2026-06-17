"""Scoring-core properties: confluence beats magnitude, correlated sources don't
double-count, evidence decays, and bearish evidence subtracts."""

from datetime import UTC, datetime, timedelta

from discovery.contributions import Contribution
from discovery.score import score_all, score_instrument
from discovery.settings import DiscoverySettings

NOW = datetime(2026, 6, 16, tzinfo=UTC)
SETTINGS = DiscoverySettings()


def _c(instrument, factor, value, *, age_days=0.0, summary="x"):
    return Contribution(
        instrument=instrument,
        factor=factor,
        value=value,
        event_time=NOW - timedelta(days=age_days),
        summary=summary,
        source="test",
        signal_id="s",
    )


def _score(*contribs):
    return score_instrument("AAA", list(contribs), now=NOW, settings=SETTINGS).score


def test_confluence_beats_a_single_strong_signal():
    # Two distinct weak factors should outrank one loud single factor.
    one_strong = _score(_c("AAA", "alpha", 0.9))
    two_weak = _score(_c("AAA", "alpha", 0.5), _c("AAA", "beta", 0.5))
    assert two_weak > one_strong


def test_correlated_sources_in_one_factor_do_not_compound():
    # Five items in the same family ≈ one (max within factor), not 5×.
    one = _score(_c("AAA", "alpha", 0.5))
    five = _score(*[_c("AAA", "alpha", 0.5) for _ in range(5)])
    assert five == one


def test_evidence_decays_with_age():
    fresh = _score(_c("AAA", "insider_activity", 0.8))
    stale = _score(_c("AAA", "insider_activity", 0.8, age_days=60))
    assert stale < fresh


def test_bearish_evidence_subtracts():
    bullish_only = _score(_c("AAA", "alpha", 0.6))
    with_bearish = _score(_c("AAA", "alpha", 0.6), _c("AAA", "beta", -0.6))
    assert with_bearish < bullish_only


def test_score_all_ranks_and_groups_by_instrument():
    candidates = score_all(
        [
            _c("AAA", "alpha", 0.3),
            _c("BBB", "alpha", 0.5),
            _c("BBB", "beta", 0.5),
        ],
        now=NOW,
        settings=SETTINGS,
    )
    assert [c.instrument for c in candidates] == ["BBB", "AAA"]
    assert all(0.0 <= c.score <= 1.0 for c in candidates)


if __name__ == "__main__":
    test_confluence_beats_a_single_strong_signal()
    test_correlated_sources_in_one_factor_do_not_compound()
    test_evidence_decays_with_age()
    test_bearish_evidence_subtracts()
    test_score_all_ranks_and_groups_by_instrument()
    print("ok")
