"""
Discovery scoring configuration.

Per-factor weight + half-life is the tunable surface of the confluence score
(ADR-012). It lives here as a code constant for the MVP — weights are *priors*,
not learned values (there are no outcome labels yet); env-override and
calibration-driven re-weighting are later-phase. Global knobs (threshold,
window, top-k, confluence bonus) are real settings so they can move per-deploy.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True)
class FactorWeight:
    weight: float  # how much this family counts, before decay
    half_life_days: float  # how fast its evidence goes stale


# Slow disclosures (insider, gov) stay material for weeks; fast/noisy sources
# (news) decay in days. Unknown factors fall back to the settings defaults.
FACTOR_WEIGHTS: dict[str, FactorWeight] = {
    "insider_activity": FactorWeight(weight=0.9, half_life_days=21.0),
    "government_exposure": FactorWeight(weight=0.6, half_life_days=30.0),
    "supply_chain": FactorWeight(weight=0.4, half_life_days=45.0),
    "news": FactorWeight(weight=0.5, half_life_days=3.0),
}


class DiscoverySettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        populate_by_name=True,
        extra="ignore",
    )

    # Lookback window for the scoring projection (days).
    window_days: int = Field(default=30, alias="DISCOVERY_WINDOW_DAYS")
    # Minimum opportunity score to surface as a candidate.
    threshold: float = Field(default=0.35, alias="DISCOVERY_THRESHOLD")
    # Max candidates returned by the ranked feed.
    top_k: int = Field(default=20, alias="DISCOVERY_TOP_K")
    # Reward for ≥2 distinct positive factors agreeing (confluence).
    confluence_bonus: float = Field(default=0.15, alias="DISCOVERY_CONFLUENCE_BONUS")
    # Fallbacks for factors absent from FACTOR_WEIGHTS.
    default_weight: float = Field(default=0.4, alias="DISCOVERY_DEFAULT_WEIGHT")
    default_half_life_days: float = Field(
        default=14.0, alias="DISCOVERY_DEFAULT_HALF_LIFE_DAYS"
    )
    # Token cap for the AI analyst pass — kept small; the analyst explains a
    # candidate, it doesn't write an essay.
    analysis_max_tokens: int = Field(default=600, alias="DISCOVERY_ANALYSIS_MAX_TOKENS")

    def weight(self, factor: str) -> float:
        fw = FACTOR_WEIGHTS.get(factor)
        return fw.weight if fw is not None else self.default_weight

    def half_life(self, factor: str) -> float:
        fw = FACTOR_WEIGHTS.get(factor)
        return fw.half_life_days if fw is not None else self.default_half_life_days
