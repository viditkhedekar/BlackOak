"""Pure macro-series domain: one observation of one series (FEDFUNDS, VIX, …)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class MacroPoint:
    series_id: str
    date: date
    value: Decimal
