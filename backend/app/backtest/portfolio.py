"""Simulated portfolio ledger for the backtester.

Tracks cash, open positions (with their live trail state from rules.PositionState), and
a realized-trade log. Marks to market on each session close for the equity curve."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.domain.rules import PositionState


@dataclass(frozen=True, slots=True)
class Trade:
    symbol: str
    side: str  # buy | sell
    trade_date: date
    shares: float
    price: float
    reason: str
    realized_pnl: float  # for sells; 0 on buys


@dataclass
class SimPortfolio:
    cash: float
    positions: dict[str, PositionState] = field(default_factory=dict)
    trades: list[Trade] = field(default_factory=list)

    def sector_weight(
        self, sector: str, sectors: dict[str, str], marks: dict[str, float]
    ) -> float:
        equity = self.equity(marks)
        if equity <= 0:
            return 0.0
        held = sum(
            pos.shares * marks.get(sym, pos.entry_price)
            for sym, pos in self.positions.items()
            if sectors.get(sym) == sector
        )
        return held / equity

    def equity(self, marks: dict[str, float]) -> float:
        holdings = sum(
            pos.shares * marks.get(sym, pos.entry_price)
            for sym, pos in self.positions.items()
        )
        return self.cash + holdings

    def buy(
        self, symbol: str, trade_date: date, shares: float, price: float, state: PositionState
    ) -> None:
        self.cash -= shares * price
        self.positions[symbol] = state
        self.trades.append(Trade(symbol, "buy", trade_date, shares, price, "entry", 0.0))

    def sell(
        self, symbol: str, trade_date: date, fraction: float, price: float, reason: str
    ) -> None:
        pos = self.positions[symbol]
        shares = pos.shares * fraction
        proceeds = shares * price
        realized = shares * (price - pos.entry_price)
        self.cash += proceeds
        self.trades.append(
            Trade(symbol, "sell", trade_date, shares, price, reason, realized)
        )
        if fraction >= 1.0:
            del self.positions[symbol]
        else:
            pos.shares -= shares
            pos.took_partial = True
