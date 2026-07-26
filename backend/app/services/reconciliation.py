"""Position reconciliation — the broker is the source of truth for what we hold.

Overwrites the local mirror from the broker's positions and removes any local rows the
broker no longer reports. Runs after every cycle and nightly; every correction is
implicitly auditable via the updated mirror + the executions ledger.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.companies import CompanyRepository
from app.db.repositories.trading import PositionRepository, ThesisRepository
from app.services.ports import BrokerClient

log = structlog.get_logger()


@dataclass
class ReconcileReport:
    synced: int = 0
    removed: list[str] = field(default_factory=list)


async def reconcile_positions(session: AsyncSession, broker: BrokerClient) -> ReconcileReport:
    import asyncio

    broker_positions = await asyncio.to_thread(broker.list_positions)
    positions_repo = PositionRepository(session)
    companies = CompanyRepository(session)
    thesis_repo = ThesisRepository(session)

    broker_symbols = {p.symbol for p in broker_positions}
    report = ReconcileReport()
    now = datetime.now(UTC)

    for p in broker_positions:
        company_id = await companies.get_id_by_symbol(p.symbol)
        if company_id is None:
            continue
        await positions_repo.upsert(
            {
                "company_id": company_id,
                "symbol": p.symbol,
                "shares": p.qty,
                "avg_entry_price": p.avg_entry_price,
                "last_synced_at": now,
            }
        )
        report.synced += 1

    # Remove local positions (and their theses) the broker no longer reports.
    for local in await positions_repo.all():
        if local.symbol not in broker_symbols:
            await positions_repo.delete_symbol(local.symbol)
            await thesis_repo.delete_symbol(local.symbol)
            report.removed.append(local.symbol)

    log.info("reconcile.done", synced=report.synced, removed=report.removed)
    return report
