"""FRED macro-series adapter using the keyless fredgraph.csv endpoint.

No API key required: https://fred.stlouisfed.org/graph/fredgraph.csv?id=SERIES
returns the full history as CSV. Missing observations arrive as "." and are skipped.
"""

from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal, InvalidOperation

import httpx
import structlog
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.domain.macro import MacroPoint

log = structlog.get_logger()

_BASE_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"


class FredMacro:
    name = "fred"

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def fetch_series(self, series_id: str, start: date, end: date) -> list[MacroPoint]:
        response = httpx.get(
            _BASE_URL,
            params={"id": series_id, "cosd": start.isoformat(), "coed": end.isoformat()},
            timeout=30.0,
            follow_redirects=True,
        )
        response.raise_for_status()

        points: list[MacroPoint] = []
        reader = csv.reader(io.StringIO(response.text))
        header = next(reader, None)
        if header is None or len(header) < 2:
            log.warning("fred.empty_response", series=series_id)
            return []

        for row in reader:
            if len(row) < 2:
                continue
            try:
                day = date.fromisoformat(row[0].strip())
                value = Decimal(row[1].strip())
            except (ValueError, InvalidOperation):
                # "." marks a missing observation — normal for market holidays.
                continue
            points.append(MacroPoint(series_id=series_id, date=day, value=value))

        points.sort(key=lambda p: p.date)
        return points
