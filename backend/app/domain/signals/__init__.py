"""Signal families for the v2 autonomous strategy (docs/ROADMAP.md R1).

``compute_signals`` runs all five families over one ``SignalInputs`` and returns raw
values grouped by family. Macro is deliberately absent here — it sets the regime (R2),
it does not score stocks. Ranking/direction happens in ``domain/strategy.py``.
"""

from __future__ import annotations

from app.domain.signals import (
    fundamentals,
    momentum,
    risk,
    technical,
    valuation,
)
from app.domain.signals.inputs import (
    SIGNAL_FAMILIES,
    EstimateValues,
    SignalInputs,
)

_FAMILY_FN = {
    "valuation": valuation.compute,
    "fundamentals": fundamentals.compute,
    "momentum": momentum.compute,
    "technical": technical.compute,
    "risk": risk.compute,
}


def compute_signals(inputs: SignalInputs) -> dict[str, dict[str, float | None]]:
    """{family: {metric: raw value | None}} for all five families."""
    return {family: fn(inputs) for family, fn in _FAMILY_FN.items()}


def data_completeness(signals: dict[str, dict[str, float | None]]) -> float:
    """Fraction of all catalogued metrics that came back non-None (the entry gate)."""
    total = sum(len(names) for names in SIGNAL_FAMILIES.values())
    present = sum(
        1
        for family, metrics in signals.items()
        for value in metrics.values()
        if value is not None
    )
    return present / total if total else 0.0


__all__ = [
    "SIGNAL_FAMILIES",
    "EstimateValues",
    "SignalInputs",
    "compute_signals",
    "data_completeness",
]
