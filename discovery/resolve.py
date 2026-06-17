"""
Entity resolution: source-specific references → canonical instrument keys.

This is the #1 risk surface in discovery (ADR-012) — a wrong resolution puts
conviction on the wrong asset. 6A signals already carry canonical symbols, so
for the MVP this is cleanup + selection, not fuzzy matching. The fuzzy
company-name → ticker path (lobbying/contracts) and its **drop-on-ambiguous**
rule will live here when the scanner sources arrive.
"""

from __future__ import annotations


def resolve_instruments(raw: list[str]) -> list[str]:
    """Canonical keys for a signal's named instruments.

    Cleans and de-duplicates; an unresolvable name is dropped rather than
    guessed. A signal that resolves to nothing yields no contributions.
    """
    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        if not item or not item.strip():
            continue
        key = item.strip().upper()
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out
