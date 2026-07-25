"""Pure market-data domain: the Bar value object and price validation.

No I/O, no SQLAlchemy, no HTTP — everything here is deterministic and unit-testable
in isolation (see docs/ARCHITECTURE.md, module rule 1).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

# A single-day move larger than this is implausible for a liquid equity and almost
# always signals an unadjusted split or a bad tick. We flag rather than silently drop.
EXTREME_MOVE_THRESHOLD = Decimal("0.50")


@dataclass(frozen=True, slots=True)
class Bar:
    """One symbol's OHLCV for one session."""

    symbol: str
    date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    adj_close: Decimal
    volume: int


@dataclass(frozen=True, slots=True)
class ValidatedBars:
    """Outcome of validating a symbol's bars: clean rows kept, bad rows quarantined."""

    symbol: str
    valid: list[Bar]
    rejected: list[tuple[Bar, str]]  # (bar, reason)
    flagged: list[tuple[Bar, str]]  # kept, but worth a human glance


def _is_coherent(bar: Bar) -> str | None:
    """Return a rejection reason if the bar is structurally impossible, else None."""
    prices = (bar.open, bar.high, bar.low, bar.close, bar.adj_close)
    # NaN slips in when a provider hasn't computed a field yet (e.g. yfinance adj_close
    # on the latest row). Reject before any comparison, which would raise on NaN.
    if any(p.is_nan() for p in prices):
        return "nan_value"
    if any(p <= 0 for p in prices):
        return "non_positive_price"
    if bar.volume < 0:
        return "negative_volume"
    if bar.high < bar.low:
        return "high_below_low"
    if not (bar.low <= bar.open <= bar.high):
        return "open_outside_range"
    if not (bar.low <= bar.close <= bar.high):
        return "close_outside_range"
    return None


def validate_bars(symbol: str, bars: list[Bar]) -> ValidatedBars:
    """Validate a symbol's bars.

    Rows that are structurally impossible are rejected (never inserted). Rows with an
    implausible day-over-day move are kept but flagged for a split/tick review. Bars are
    processed in chronological order so the move check compares against the prior close.
    """
    ordered = sorted(bars, key=lambda b: b.date)
    valid: list[Bar] = []
    rejected: list[tuple[Bar, str]] = []
    flagged: list[tuple[Bar, str]] = []

    prev_close: Decimal | None = None
    for bar in ordered:
        reason = _is_coherent(bar)
        if reason is not None:
            rejected.append((bar, reason))
            continue
        if prev_close is not None and prev_close > 0:
            move = abs(bar.close - prev_close) / prev_close
            if move > EXTREME_MOVE_THRESHOLD:
                flagged.append((bar, f"extreme_move_{move:.2f}"))
        valid.append(bar)
        prev_close = bar.close

    return ValidatedBars(symbol=symbol, valid=valid, rejected=rejected, flagged=flagged)
