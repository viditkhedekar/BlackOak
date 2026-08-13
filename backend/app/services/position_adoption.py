"""Adopt broker positions the engine has no thesis for.

The broker is the source of truth for what we hold, but the *sell* rules are measured
against an entry thesis (stop, target, trail state). A position with no thesis was
therefore invisible to ``_load_positions``: it could never be sold, no matter how far it
fell, and its notional was missing from the sector totals that gate new entries.

Positions arrive this way whenever the book and the ledger diverge — a position opened
before the engine ran, a thesis dropped by a full exit whose sell later failed, or a
database restored without its theses. Reconciliation syncs the shares but never writes a
thesis, so nothing else closes this gap.

Adoption starts management from now rather than pretending to know the past:

* ``entry_price`` is the broker's real cost basis, so P&L stays honest.
* stop and target come from the current ATR, the same multiples a fresh entry would use.
* ``highest_close`` starts at the entry/close max rather than a guessed post-entry high.
  Overstating it would place the chandelier trail above the market and sell the position
  on the very next cycle — an invented trade on invented state.
* the entry scores stay NULL: we genuinely do not know what they were, and the sell rules
  already treat a missing entry score as "no fundamentals-drop signal" rather than a zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.trading import PositionRepository, ThesisRepository
from app.domain.decision import SymbolCycleData
from app.domain.sizing import STOP_ATR_MULT, TARGET_ATR_MULT

log = structlog.get_logger()


@dataclass
class AdoptionReport:
    adopted: list[str] = field(default_factory=list)
    unmanageable: list[str] = field(default_factory=list)  # no ATR — cannot set a stop


async def adopt_orphan_positions(
    session: AsyncSession, cycle_data: dict[str, SymbolCycleData]
) -> AdoptionReport:
    """Write a thesis for every held position that lacks one, so the sell rules see it."""
    theses = {t.symbol for t in await ThesisRepository(session).all()}
    thesis_repo = ThesisRepository(session)
    report = AdoptionReport()

    for mirror in await PositionRepository(session).all():
        if mirror.symbol in theses:
            continue

        data = cycle_data.get(mirror.symbol)
        if data is None or data.atr is None or data.atr <= 0:
            # Without an ATR there is no defensible stop distance. Inventing one would put
            # a fabricated exit on a real position, so leave it and surface it instead.
            report.unmanageable.append(mirror.symbol)
            continue

        entry_price = float(mirror.avg_entry_price)
        await thesis_repo.upsert(
            {
                "symbol": mirror.symbol,
                "entry_price": entry_price,
                "atr_at_entry": data.atr,
                "stop_price": entry_price - STOP_ATR_MULT * data.atr,
                "target_price": entry_price + TARGET_ATR_MULT * data.atr,
                "entry_composite": None,
                "entry_fundamentals_score": None,
                "took_partial": False,
                "highest_close": max(entry_price, data.bar_close),
                "reversal_days": 0,
            }
        )
        report.adopted.append(mirror.symbol)

    if report.adopted or report.unmanageable:
        log.info(
            "position_adoption.done",
            adopted=len(report.adopted),
            symbols=report.adopted,
            unmanageable=report.unmanageable,
        )
    return report
