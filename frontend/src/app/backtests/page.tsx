"use client";

import ReactECharts from "echarts-for-react";
import { useState } from "react";
import type { BacktestDetail } from "@/lib/api/client";
import { useBacktest, useBacktests } from "@/lib/hooks/useCompanies";

function pct(v: number | null | undefined): string {
  return v == null ? "—" : `${(v * 100).toFixed(2)}%`;
}
function num(v: number | null | undefined, d = 2): string {
  return v == null ? "—" : v.toFixed(d);
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-line bg-surface p-3">
      <div className="font-mono text-[10px] uppercase tracking-widest text-muted">{label}</div>
      <div className="mt-1 text-lg font-semibold tabular-nums">{value}</div>
    </div>
  );
}

function EquityChart({ detail }: { detail: BacktestDetail }) {
  const days = detail.equity_curve.map((p) => p.day);
  const equity = detail.equity_curve.map((p) => p.equity);
  const option = {
    grid: { left: 60, right: 20, top: 20, bottom: 40 },
    tooltip: { trigger: "axis" },
    xAxis: { type: "category", data: days, axisLabel: { color: "#6b7688", fontSize: 10 } },
    yAxis: {
      type: "value", scale: true, axisLabel: { color: "#6b7688", fontSize: 10 },
      splitLine: { lineStyle: { color: "#1c2433" } },
    },
    series: [
      {
        type: "line", data: equity, showSymbol: false,
        lineStyle: { color: "#d4a843", width: 2 }, areaStyle: { color: "#d4a84322" },
      },
    ],
  };
  return <ReactECharts option={option} style={{ height: 300 }} notMerge />;
}

export default function BacktestLab() {
  const runs = useBacktests();
  const [selected, setSelected] = useState<string | null>(null);
  const activeId = selected ?? runs.data?.[0]?.id ?? "";
  const detail = useBacktest(activeId);
  const m = detail.data?.summary.metrics as Record<string, unknown> | undefined;
  const benchmarks = (m?.benchmarks ?? []) as Array<Record<string, unknown>>;

  return (
    <div className="mx-auto max-w-6xl">
      <h1 className="mb-1 text-2xl font-semibold">Backtest Lab</h1>
      <p className="mb-4 text-sm text-muted">
        Historical runs of the exact strategy the live engine trades — measured against SPY
        and equal-weight RSP, with costs modeled.
      </p>

      <div className="mb-4 flex flex-wrap gap-2">
        {runs.data?.map((r) => (
          <button
            key={r.id}
            onClick={() => setSelected(r.id)}
            className={`rounded px-3 py-1.5 font-mono text-xs ${
              r.id === activeId ? "bg-accent text-background" : "bg-line/40 text-muted hover:bg-line"
            }`}
          >
            {r.start_date} → {r.end_date}
          </button>
        ))}
        {runs.data?.length === 0 && (
          <p className="text-sm text-muted">No backtest runs yet — run `cli backtest`.</p>
        )}
      </div>

      {detail.data && m && (
        <>
          <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <Metric label="Total Return" value={pct(m.total_return as number)} />
            <Metric label="CAGR" value={pct(m.cagr as number)} />
            <Metric label="Sharpe" value={num(m.sharpe as number)} />
            <Metric label="Max DD" value={pct(m.max_drawdown as number)} />
            <Metric label="Trades" value={String(m.trades ?? "—")} />
            <Metric label="Cost Drag" value={pct(m.cost_drag as number)} />
          </div>

          <div className="mb-4 rounded-lg border border-line bg-surface p-4">
            <h2 className="mb-2 font-mono text-xs uppercase tracking-widest text-muted">
              Equity curve
            </h2>
            <EquityChart detail={detail.data} />
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <div className="rounded-lg border border-line bg-surface p-4">
              <h2 className="mb-3 font-mono text-xs uppercase tracking-widest text-muted">
                Vs benchmarks
              </h2>
              <table className="w-full text-sm">
                <tbody>
                  {benchmarks.map((b) => (
                    <tr key={String(b.name)} className="border-b border-line/40">
                      <td className="py-2 font-mono font-semibold">{String(b.name)}</td>
                      <td className="py-2 text-right text-muted">
                        return {pct(b.total_return as number)}
                      </td>
                      <td className="py-2 text-right">
                        excess{" "}
                        <span
                          className={
                            (b.excess_return as number) >= 0 ? "text-positive" : "text-negative"
                          }
                        >
                          {pct(b.excess_return as number)}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-3 font-mono text-[10px] text-muted">
                regime days: {JSON.stringify(m.regime_days)}
              </p>
            </div>

            <div className="rounded-lg border border-line bg-surface">
              <h2 className="border-b border-line px-4 py-3 font-mono text-xs uppercase tracking-widest text-muted">
                Trades ({detail.data.trades.length})
              </h2>
              <div className="max-h-[280px] overflow-y-auto">
                {detail.data.trades.map((t, i) => (
                  <div
                    key={i}
                    className="grid grid-cols-[60px_50px_1fr_90px] gap-2 border-b border-line/40 px-4 py-1.5 text-xs"
                  >
                    <span className="font-mono font-semibold">{t.symbol}</span>
                    <span className={t.side === "buy" ? "text-positive" : "text-negative"}>
                      {t.side}
                    </span>
                    <span className="truncate text-muted">{t.reason}</span>
                    <span
                      className={`text-right font-mono ${
                        t.realized_pnl > 0 ? "text-positive" : t.realized_pnl < 0 ? "text-negative" : "text-muted"
                      }`}
                    >
                      {t.realized_pnl !== 0 ? `$${t.realized_pnl.toFixed(0)}` : ""}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
