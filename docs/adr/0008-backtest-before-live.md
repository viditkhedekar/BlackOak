# ADR-0008: One brain, two clocks — backtester before the live loop

**Status:** Accepted · 2026-07-25

## Context
An autonomous strategy that cannot be simulated cannot be trusted or tuned. The classic failure mode is two codebases — one for backtesting, one for live — that silently diverge, so backtest results never materialize live. We also need to tune weights and thresholds without overfitting, and to prove the live engine has no lookahead bug.

## Decision
- **Shared domain, two drivers.** The live decision engine and the backtester both call the *same* pure functions in `domain/strategy.py`, `domain/sizing.py`, and the signal engines, through a `DataWindow` abstraction that exposes only data with timestamp ≤ *t*. Neither driver contains strategy logic.
- **Build order:** the backtester (R3) ships **before** the live execution engine (R4). Autonomy is not switched on until a walk-forward backtest and a backtest/live parity test both pass.
- **Parity is a CI test.** A recorded live trading day, replayed through the backtester, must produce byte-identical decisions.
- **Point-in-time discipline.** Fundamentals are usable in a backtest only 45 days after fiscal period end (yfinance is not point-in-time); all signals read strictly from data ≤ *t*. A no-lookahead harness mutates future bars and asserts decisions at *t* are unchanged.
- **Overfitting controls.** ~10 free parameters maximum; tuned only on 2015–2021, validated on 2022–2024, with 2025+ held out untouched; every parameter set is a versioned `strategy_config` row.

## Consequences
- Survivorship bias (backtesting today's S&P 500 constituents) is documented openly and sanity-checked against RSP; a point-in-time constituent history is a fast-follow, not a v2 blocker.
- Cost realism is mandatory: 5 bps slippage + half-spread + an ATR-scaled impact bump on volume-spike entries; reports always show cost drag explicitly.
- The `DataWindow` seam is the single most important design constraint in the codebase — any strategy code that reaches around it to touch a repository or the clock directly is a bug.
