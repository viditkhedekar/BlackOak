"""The decision journal must produce a realistic mix of actions and explain every skip.

The regression these lock: the pipeline once emitted `skip / composite_below_min` for
essentially the whole S&P 500, because the entry gate compared an absolute threshold of 70
against a composite that is a mean of percentiles and so never leaves the mid-50s. A
journal where one reason code covers the universe is indistinguishable from a broken one,
so these tests assert on the *distribution* of outcomes, not just that the code runs.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.domain.decision import SymbolCycleData, plan_cycle
from app.domain.rules import (
    GATE_HARD,
    GATE_PORTFOLIO,
    GATE_SCORE,
    MAX_ENTRIES_PER_DAY,
    PositionState,
)
from app.domain.signals.inputs import SIGNAL_FAMILIES
from app.domain.strategy import INVERSE_METRICS, StrategyCompany, fuse_scores
from app.services.decision_engine import _decision_rows

_N = 60
_SECTORS = ["Tech", "Health", "Financials", "Energy", "Staples"]

# Each name falls into one of three technical shapes so the top of the book exercises the
# post-score gates rather than every candidate failing at the same one.
_BUY_READY, _DOWNTREND, _NO_TRIGGER = 0, 1, 2


def _shape(i: int) -> int:
    return i % 3


def _closes(i: int) -> list[float]:
    if _shape(i) == _DOWNTREND:
        return [130.0 - j * 0.5 for j in range(60)]  # ends below its 50DMA
    return [100.0 + j * 0.5 for j in range(60)]  # steady rise, ends above


def _signals(i: int) -> dict[str, dict[str, float | None]]:
    """Quality falls off monotonically with i, so S0 is the strongest name."""
    quality = float(_N - i)
    signals: dict[str, dict[str, float | None]] = {
        family: {m: (-quality if m in INVERSE_METRICS else quality) for m in metrics}
        for family, metrics in SIGNAL_FAMILIES.items()
    }
    bullish = _shape(i) != _NO_TRIGGER
    signals["technical"]["macd_hist"] = 0.8 if bullish else -0.8
    signals["momentum"]["breakout_strength"] = 1.5 if bullish else -1.5
    signals["fundamentals"]["interest_coverage"] = 8.0
    return signals


def _cycle_data(regime: str = "neutral") -> dict[str, SymbolCycleData]:
    companies = [
        StrategyCompany(f"S{i}", _SECTORS[i % len(_SECTORS)], _signals(i)) for i in range(_N)
    ]
    scores = {s.symbol: s for s in fuse_scores(companies, regime)}
    data: dict[str, SymbolCycleData] = {}
    for i, c in enumerate(companies):
        closes = _closes(i)
        last = closes[-1]
        data[c.symbol] = SymbolCycleData(
            symbol=c.symbol, sector=c.sector,
            bar_open=last, bar_high=last + 1.0, bar_low=last - 1.0, bar_close=last,
            closes=closes, signals=c.signals, score=scores[c.symbol], atr=0.02 * last,
        )
    return data


def _plan(data: dict[str, SymbolCycleData] | None = None, **over: object):
    data = data if data is not None else _cycle_data()
    kwargs: dict[str, object] = dict(
        positions={}, equity=100_000.0, cash=100_000.0,
        sector_notional={}, entries_today=0, n_scored=len(data),
    )
    kwargs.update(over)
    return plan_cycle(data, **kwargs)  # type: ignore[arg-type]


# --- the decision mix ------------------------------------------------------

def test_cycle_produces_buys_from_a_healthy_universe() -> None:
    plan = _plan()
    assert plan.entries, "a well-scored universe must yield entries"
    assert len(plan.entries) <= MAX_ENTRIES_PER_DAY


def test_skip_reasons_are_not_collapsed_onto_one_code() -> None:
    """The bug signature: every name failing at the same gate."""
    plan = _plan()
    reasons = {s.reason for s in plan.skips}
    assert len(reasons) >= 3, f"journal collapsed onto {reasons}"
    assert "composite_below_min" in reasons  # the bottom of the book, legitimately
    # ...but it must not be the *only* story.
    below_min = sum(1 for s in plan.skips if s.reason == "composite_below_min")
    assert below_min < len(plan.skips), "composite_below_min swallowed the whole universe"


def test_top_of_book_is_rejected_by_post_score_gates() -> None:
    """Names that clear the score gate must be judged on their technicals, which is only
    observable once the composite gate stops rejecting everything first."""
    plan = _plan()
    reasons = {s.reason for s in plan.skips}
    assert {"below_50dma", "no_technical_trigger"} & reasons


def test_all_three_gate_kinds_are_represented() -> None:
    plan = _plan(entries_today=MAX_ENTRIES_PER_DAY)  # forces the portfolio limit
    kinds = {s.gate_kind for s in plan.skips}
    assert {GATE_SCORE, GATE_HARD, GATE_PORTFOLIO} <= kinds, kinds


def test_cycle_produces_holds_and_sells_for_open_positions() -> None:
    data = _cycle_data()
    healthy = data["S0"]
    stopped = data["S3"]
    positions = {
        "S0": PositionState(
            symbol="S0", entry_price=110.0, shares=10.0, atr_at_entry=2.0,
            stop_price=100.0, target_price=200.0, entry_composite=60.0,
            entry_fundamentals_score=70.0, highest_close=healthy.bar_close,
        ),
        # Stop sits above this bar's low, so the position must exit.
        "S3": PositionState(
            symbol="S3", entry_price=140.0, shares=10.0, atr_at_entry=2.0,
            stop_price=stopped.bar_close + 5.0, target_price=200.0, entry_composite=60.0,
            entry_fundamentals_score=70.0, highest_close=stopped.bar_close,
        ),
    }
    plan = _plan(data, positions=positions)
    by_symbol = {e.symbol: e.action for e in plan.exits}

    assert by_symbol["S0"].fraction == 0.0 and by_symbol["S0"].reason == "hold"
    assert by_symbol["S3"].fraction == 1.0
    assert by_symbol["S3"].reason in {"stop_loss", "stop_gap"}


def test_held_names_are_not_re_entered() -> None:
    data = _cycle_data()
    positions = {
        "S0": PositionState(
            symbol="S0", entry_price=110.0, shares=10.0, atr_at_entry=2.0,
            stop_price=100.0, target_price=200.0, entry_composite=60.0,
            entry_fundamentals_score=70.0, highest_close=data["S0"].bar_close,
        )
    }
    plan = _plan(data, positions=positions)
    assert "S0" not in {e.symbol for e in plan.entries}
    assert "S0" not in {s.symbol for s in plan.skips}


# --- skip evidence ---------------------------------------------------------

def test_skip_records_carry_the_deciding_numbers() -> None:
    plan = _plan()
    below_min = [s for s in plan.skips if s.reason == "composite_below_min"]
    assert below_min
    for skip in below_min:
        assert skip.detail["composite_percentile"] is not None
        assert skip.detail["min_composite_percentile"] == 70.0
        assert skip.detail["shortfall"] > 0
        assert skip.gate_kind == GATE_SCORE


def test_unscorable_name_is_journaled_as_insufficient_data() -> None:
    """A name with no usable signals must still appear in the journal, and must say the
    data was missing rather than blaming a score threshold it never reached."""
    data = _cycle_data()
    blank = StrategyCompany(
        "BLANK", "Tech", {f: {m: None for m in ms} for f, ms in SIGNAL_FAMILIES.items()}
    )
    scored = {
        s.symbol: s
        for s in fuse_scores(
            [blank, *[StrategyCompany(f"S{i}", _SECTORS[i % 5], _signals(i))
                      for i in range(_N)]],
            "neutral",
        )
    }
    closes = _closes(0)
    data["BLANK"] = SymbolCycleData(
        symbol="BLANK", sector="Tech",
        bar_open=closes[-1], bar_high=closes[-1] + 1, bar_low=closes[-1] - 1,
        bar_close=closes[-1], closes=closes, signals=blank.signals,
        score=scored["BLANK"], atr=2.0,
    )
    plan = _plan(data)

    blank_skip = next(s for s in plan.skips if s.symbol == "BLANK")
    assert blank_skip.reason == "insufficient_data"
    assert blank_skip.gate_kind == GATE_HARD
    assert blank_skip.detail["unscored"] is True


# --- journal rows: near-miss detail plus a rollup --------------------------

def _rows(plan, data: dict[str, SymbolCycleData]) -> list[dict[str, object]]:
    return _decision_rows(
        uuid.uuid4(), datetime(2026, 7, 26, 15, 0, tzinfo=UTC), "neutral",
        plan, data, halt_reason=None, entries_locked=False,
    )


def test_journal_covers_every_skipped_symbol_exactly_once() -> None:
    data = _cycle_data()
    plan = _plan(data)
    rows = _rows(plan, data)

    detailed = [r for r in rows if r["action"] == "skip" and r["symbol"] != "*"]
    summary = [r for r in rows if r["reason"] == "skip_summary"]
    assert len(summary) == 1

    counted = sum(summary[0]["evidence"]["by_reason"].values())  # type: ignore[index]
    assert len(detailed) + counted == len(plan.skips)
    assert len({r["symbol"] for r in detailed}) == len(detailed)  # no duplicates


def test_near_miss_skips_carry_full_diagnostics() -> None:
    data = _cycle_data()
    plan = _plan(data)
    rows = _rows(plan, data)
    detailed = [r for r in rows if r["action"] == "skip" and r["symbol"] != "*"]

    assert detailed, "names in contention must be journaled individually"
    for row in detailed:
        ev = row["evidence"]
        assert isinstance(ev, dict)
        assert ev["gate_kind"] in {GATE_SCORE, GATE_HARD, GATE_PORTFOLIO}
        assert "composite" in ev and "composite_percentile" in ev
        assert ev["min_composite_percentile"] == 70.0
        assert "rank_threshold" in ev and "data_completeness" in ev
        assert "families" in ev and "detractors" in ev and "weakest_metrics" in ev
        assert ev["metrics_applicable"] > 0


def test_rollup_summarises_the_rest_by_reason_and_gate_kind() -> None:
    data = _cycle_data()
    plan = _plan(data)
    summary = next(r for r in _rows(plan, data) if r["reason"] == "skip_summary")
    ev = summary["evidence"]

    assert isinstance(ev, dict)
    assert summary["symbol"] == "*" and summary["action"] == "skip"
    assert ev["n_skipped"] > 0
    assert sum(ev["by_reason"].values()) == ev["n_skipped"]
    assert sum(ev["by_gate_kind"].values()) == ev["n_skipped"]
    assert ev["rank_threshold"] == plan.rank_threshold


def test_journal_bounds_row_count_well_below_universe_size() -> None:
    """~490 fully-detailed skip rows per cycle would drown the journal."""
    data = _cycle_data()
    plan = _plan(data)
    rows = _rows(plan, data)
    assert len(rows) < len(data) // 2


def test_buy_rows_explain_themselves_too() -> None:
    data = _cycle_data()
    plan = _plan(data)
    buys = [r for r in _rows(plan, data) if r["action"] == "buy"]

    assert buys
    for row in buys:
        ev = row["evidence"]
        assert isinstance(ev, dict)
        assert ev["composite_percentile"] >= ev["min_composite_percentile"]
        assert ev["rank"] <= ev["rank_threshold"]
        assert "families" in ev and "shares" in ev
