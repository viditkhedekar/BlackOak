"""Ranking-quality measurement: rank IC and decile spread.

Backtest P&L answers "did this book make money", which on a two-year sample is mostly
noise. The question the scoring engine is actually responsible for is narrower and much
more measurable: **does a better composite rank predict a better forward return?**

For each evaluation date we fuse the whole universe exactly as the live engine does,
then correlate composite rank against the realised forward return over ``horizon``
sessions (Spearman, i.e. Pearson on ranks — the information coefficient). We also bucket
the universe into deciles and report each decile's mean forward return, because a
strategy that only buys the top decile cares about the top of the distribution, not the
average fit across it.

Reading the output:
  * ``mean_ic`` — average IC. Cross-sectional equity signals live around 0.02-0.05;
    anything above 0.10 sustained is suspicious and usually means lookahead.
  * ``t_stat`` — mean_ic / stderr across dates. |t| > 2 is the usual bar for "real".
  * ``hit_rate`` — fraction of dates with positive IC. ~0.5 means no edge.
  * ``top_minus_bottom`` — decile 1 mean return minus decile 10. The economically
    meaningful number.
  * ``monotonicity`` — Spearman of decile index vs decile mean return. 1.0 = perfectly
    ordered deciles, which is what "the ranking works" actually looks like.

Pure and deterministic: it takes loaded BacktestData and returns numbers. No I/O.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from datetime import date
from statistics import fmean, pstdev

import structlog

from app.backtest.data_window import BacktestData, DataWindow
from app.domain.regime import build_features, classify_raw, confirmed_regime
from app.domain.signals import compute_signals
from app.domain.stats import sma
from app.domain.strategy import StrategyCompany, fuse_scores

log = structlog.get_logger()

WARMUP_BARS = 200
N_DECILES = 10


@dataclass(frozen=True, slots=True)
class ICPoint:
    """One evaluation date."""

    as_of: date
    regime: str
    n: int
    ic: float
    decile_returns: list[float]  # index 0 = best-ranked decile
    top_minus_bottom: float
    # Per-family IC on the same date. This is what makes the regime weights an evidence
    # question rather than a matter of taste: a family with persistently negative IC is
    # being weighted in the wrong direction, not merely weighted too heavily.
    family_ic: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ICReport:
    horizon: int
    points: list[ICPoint] = field(default_factory=list)

    @property
    def mean_ic(self) -> float:
        return fmean([p.ic for p in self.points]) if self.points else 0.0

    @property
    def ic_sd(self) -> float:
        return pstdev([p.ic for p in self.points]) if len(self.points) > 1 else 0.0

    @property
    def t_stat(self) -> float:
        """mean_ic / standard error. |t| > 2 is the conventional significance bar."""
        if len(self.points) < 2 or self.ic_sd == 0:
            return 0.0
        return float(self.mean_ic / (self.ic_sd / (len(self.points) ** 0.5)))

    @property
    def hit_rate(self) -> float:
        if not self.points:
            return 0.0
        return sum(1 for p in self.points if p.ic > 0) / len(self.points)

    @property
    def decile_means(self) -> list[float]:
        """Mean forward return per decile, averaged over dates. Index 0 = best ranked."""
        if not self.points:
            return []
        return [
            fmean([p.decile_returns[i] for p in self.points]) for i in range(N_DECILES)
        ]

    @property
    def top_minus_bottom(self) -> float:
        return fmean([p.top_minus_bottom for p in self.points]) if self.points else 0.0

    @property
    def monotonicity(self) -> float:
        """Spearman of decile index vs mean return: 1.0 = perfectly ordered deciles."""
        means = self.decile_means
        if len(means) < 2:
            return 0.0
        # Deciles are already ordered best-first, so the ideal ranking is 0..9 descending.
        return _spearman(list(range(len(means))), [-m for m in means])

    def family_ic(self) -> dict[str, float]:
        """Mean IC per family across dates — the evidence base for the regime weights."""
        acc: dict[str, list[float]] = {}
        for p in self.points:
            for fam, ic in p.family_ic.items():
                acc.setdefault(fam, []).append(ic)
        return {k: round(fmean(v), 4) for k, v in sorted(acc.items())}

    def family_ic_by_regime(self) -> dict[str, dict[str, float]]:
        acc: dict[str, dict[str, list[float]]] = {}
        for p in self.points:
            for fam, ic in p.family_ic.items():
                acc.setdefault(p.regime, {}).setdefault(fam, []).append(ic)
        return {
            reg: {fam: round(fmean(v), 4) for fam, v in sorted(fams.items())}
            for reg, fams in acc.items()
        }

    def by_regime(self) -> dict[str, float]:
        out: dict[str, list[float]] = {}
        for p in self.points:
            out.setdefault(p.regime, []).append(p.ic)
        return {k: round(fmean(v), 4) for k, v in out.items()}

    def to_dict(self) -> dict[str, object]:
        return {
            "horizon": self.horizon,
            "dates": len(self.points),
            "mean_ic": round(self.mean_ic, 4),
            "ic_sd": round(self.ic_sd, 4),
            "t_stat": round(self.t_stat, 2),
            "hit_rate": round(self.hit_rate, 3),
            "top_minus_bottom": round(self.top_minus_bottom, 4),
            "monotonicity": round(self.monotonicity, 3),
            "decile_means": [round(m, 4) for m in self.decile_means],
            "ic_by_regime": self.by_regime(),
            "family_ic": self.family_ic(),
            "family_ic_by_regime": self.family_ic_by_regime(),
        }


def _ranks(values: list[float]) -> list[float]:
    """Ascending ranks with ties averaged."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        shared = (i + j) / 2 + 1
        for k in range(i, j + 1):
            out[order[k]] = shared
        i = j + 1
    return out


def _pearson(a: list[float], b: list[float]) -> float:
    n = len(a)
    if n < 2:
        return 0.0
    ma, mb = fmean(a), fmean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=True))
    da = sum((x - ma) ** 2 for x in a) ** 0.5
    db = sum((y - mb) ** 2 for y in b) ** 0.5
    return num / (da * db) if da and db else 0.0


def _spearman(a: list[float], b: list[float]) -> float:
    return _pearson(_ranks(a), _ranks(b))


def _forward_return(
    data: BacktestData, symbol: str, as_of: date, horizon: int
) -> float | None:
    """Return from the close on/just before ``as_of`` to ``horizon`` sessions later."""
    series = data.series.get(symbol)
    if series is None:
        return None
    i = bisect_right(series.dates, as_of) - 1
    j = i + horizon
    if i < 0 or j >= len(series.closes):
        return None
    start, end = series.closes[i], series.closes[j]
    if start <= 0:
        return None
    return end / start - 1.0


def _deciles(pairs: list[tuple[float, float]]) -> tuple[list[float], float]:
    """``pairs`` = (composite, forward_return). Returns per-decile means, best first."""
    ordered = [fr for _, fr in sorted(pairs, key=lambda p: -p[0])]
    n = len(ordered)
    means: list[float] = []
    for d in range(N_DECILES):
        lo, hi = d * n // N_DECILES, (d + 1) * n // N_DECILES
        chunk = ordered[lo:hi]
        means.append(fmean(chunk) if chunk else 0.0)
    return means, means[0] - means[-1]


def evaluate_ranking(
    data: BacktestData,
    start: date,
    end: date,
    horizon: int = 21,
    step: int = 21,
    weights_by_regime: dict[str, dict[str, float]] | None = None,
) -> ICReport:
    """Walk the calendar, fusing the universe and scoring rank vs forward return.

    ``step`` spaces the evaluation dates so consecutive observations barely overlap;
    with the default both are one trading month.
    """
    calendar = data.trading_dates()
    lo = bisect_left(calendar, start)
    hi = bisect_right(calendar, end)
    points: list[ICPoint] = []
    raw_history: list[str] = []
    prev_confirmed: str | None = None
    symbols = list(data.series)

    for idx in range(max(lo, WARMUP_BARS), hi, step):
        as_of = calendar[idx]
        window = DataWindow(data, as_of)

        companies: list[StrategyCompany] = []
        above = below = 0
        for sym in symbols:
            inputs = window.signal_inputs(sym)
            if inputs is None or len(inputs.closes) < WARMUP_BARS:
                continue
            companies.append(StrategyCompany(sym, inputs.sector, compute_signals(inputs)))
            ma200 = sma(inputs.closes, 200)
            if ma200 is not None:
                if inputs.closes[-1] > ma200:
                    above += 1
                else:
                    below += 1
        if len(companies) < N_DECILES:
            continue

        breadth = above / (above + below) if (above + below) else None
        features = build_features(
            window.vix_series(), window.t10y2y(), window.spy_closes(), breadth
        )
        today_raw, _, _ = classify_raw(features)
        raw_history.append(today_raw)
        regime = confirmed_regime(raw_history[-4:], prev_confirmed)
        prev_confirmed = regime

        pairs: list[tuple[float, float]] = []
        fam_pairs: dict[str, list[tuple[float, float]]] = {}
        override = weights_by_regime.get(regime) if weights_by_regime else None
        for score in fuse_scores(companies, regime, weights=override):
            fwd = _forward_return(data, score.symbol, as_of, horizon)
            if fwd is None:
                continue
            if score.composite is not None:
                pairs.append((score.composite, fwd))
            for fam, fam_score in score.families.items():
                if fam_score is not None:
                    fam_pairs.setdefault(fam, []).append((fam_score, fwd))

        if len(pairs) < N_DECILES:
            continue
        decile_means, spread = _deciles(pairs)
        points.append(
            ICPoint(
                as_of=as_of,
                regime=regime,
                n=len(pairs),
                ic=round(_spearman([c for c, _ in pairs], [f for _, f in pairs]), 4),
                decile_returns=decile_means,
                top_minus_bottom=spread,
                family_ic={
                    fam: round(_spearman([s for s, _ in fp], [f for _, f in fp]), 4)
                    for fam, fp in fam_pairs.items()
                    if len(fp) >= N_DECILES
                },
            )
        )
        log.info("rank_ic.date", as_of=str(as_of), regime=regime, n=len(pairs),
                 ic=points[-1].ic)

    return ICReport(horizon=horizon, points=points)
