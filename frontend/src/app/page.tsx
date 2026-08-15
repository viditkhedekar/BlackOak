"use client";

import Link from "next/link";
import { EquityCurve } from "@/components/charts/EquityCurve";
import { NextCycleTimer } from "@/components/features/NextCycleTimer";
import { RegimeBadge } from "@/components/features/RegimeBadge";
import {
  useDecisions,
  usePerformance,
  usePortfolio,
  useRegime,
  useSchedule,
} from "@/lib/hooks/useCompanies";
import { scoreColor, scoreText } from "@/lib/scoreColor";

const ACTION_COLOR: Record<string, string> = {
  buy: "hsl(140,60%,55%)", sell: "hsl(0,65%,60%)", hold: "hsl(210,10%,60%)",
  skip: "hsl(45,55%,58%)", blocked: "hsl(280,45%,62%)",
};

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-lg border border-line bg-surface p-4">
      <div className="font-mono text-[10px] uppercase tracking-widest text-muted">{label}</div>
      <div className="mt-1 text-xl font-semibold tabular-nums">{value}</div>
      {sub && <div className="font-mono text-[10px] text-muted">{sub}</div>}
    </div>
  );
}

export default function CommandCenter() {
  const regime = useRegime();
  const portfolio = usePortfolio();
  const decisions = useDecisions();
  const performance = usePerformance();
  const schedule = useSchedule();

  const flags = (regime.data?.features?.flags ?? {}) as Record<string, boolean>;
  const bearish = Object.entries(flags).filter(([, v]) => v).map(([k]) => k);
  const equity = portfolio.data?.equity;
  const cash = portfolio.data?.cash;
  const positions = portfolio.data?.positions ?? [];

  return (
    <div className="mx-auto max-w-6xl">
      <div className="mb-4 flex items-end justify-between">
        <h1 className="text-2xl font-semibold">Command Center</h1>
        <div className="flex items-center gap-2 text-xs text-muted">
          market regime <RegimeBadge label={regime.data?.label} />
          {regime.data?.bearish_count != null && (
            <span className="font-mono">({regime.data.bearish_count}/4 bearish)</span>
          )}
        </div>
      </div>

      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <Stat
          label="Equity"
          value={equity != null ? `$${equity.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : "—"}
        />
        <Stat
          label="Cash"
          value={cash != null ? `$${cash.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : "—"}
          sub={equity && cash != null ? `${Math.round((cash / equity) * 100)}% cash` : undefined}
        />
        <Stat label="Positions" value={String(positions.length)} />
        <Stat
          label="Regime signals"
          value={bearish.length ? `${bearish.length} bearish` : "clear"}
          sub={bearish.join(", ") || "no bearish flags"}
        />
        {schedule.data ? (
          <NextCycleTimer data={schedule.data} dataUpdatedAt={schedule.dataUpdatedAt} />
        ) : (
          <Stat label="Next trades" value="—" sub="loading schedule…" />
        )}
      </div>

      <div className="mb-6 rounded-lg border border-line bg-surface">
        {performance.isLoading ? (
          <p className="px-4 py-10 text-sm text-muted">Loading equity curve…</p>
        ) : performance.isError ? (
          <p className="px-4 py-10 text-sm text-negative">Failed to load performance.</p>
        ) : (performance.data?.points.length ?? 0) > 0 ? (
          <EquityCurve data={performance.data!} />
        ) : (
          <div className="px-4 py-10">
            <div className="font-mono text-[10px] uppercase tracking-widest text-muted">
              Portfolio value
            </div>
            <p className="mt-2 text-sm text-muted">
              No equity history yet — the worker marks equity every 15 minutes during the
              session. Run{" "}
              <code className="font-mono text-accent">
                uv run python -m app.cli backfill-equity
              </code>{" "}
              to seed the curve from the broker&apos;s own account history.
            </p>
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="rounded-lg border border-line bg-surface">
          <div className="border-b border-line px-4 py-3">
            <h2 className="font-mono text-xs uppercase tracking-widest text-muted">Positions</h2>
          </div>
          {positions.length === 0 ? (
            <p className="px-4 py-6 text-sm text-muted">
              Flat — the engine holds no positions right now.
            </p>
          ) : (
            <table className="w-full text-sm">
              <tbody>
                {positions.map((p) => (
                  <tr key={p.symbol} className="border-b border-line/50">
                    <td className="px-4 py-2 font-mono font-semibold">{p.symbol}</td>
                    <td className="px-2 py-2 text-right font-mono text-xs text-muted">
                      {p.shares.toFixed(2)} sh
                    </td>
                    <td className="px-2 py-2 text-right font-mono text-xs">
                      @ ${p.avg_entry_price.toFixed(2)}
                    </td>
                    <td className="px-4 py-2 text-right">
                      {p.entry_composite != null && (
                        <span
                          className="rounded px-2 py-0.5 font-mono text-[11px]"
                          style={{
                            backgroundColor: scoreColor(p.entry_composite),
                            color: scoreText(p.entry_composite),
                          }}
                        >
                          {Math.round(p.entry_composite)}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="rounded-lg border border-line bg-surface">
          <div className="flex items-center justify-between border-b border-line px-4 py-3">
            <h2 className="font-mono text-xs uppercase tracking-widest text-muted">
              Live decision feed
            </h2>
            <Link href="/journal" className="font-mono text-[10px] text-accent hover:underline">
              full journal →
            </Link>
          </div>
          <div className="max-h-[360px] overflow-y-auto">
            {(decisions.data ?? []).slice(0, 25).map((d, i) => {
              const color = ACTION_COLOR[d.action] ?? "var(--muted)";
              return (
                <div
                  key={`${d.cycle_id}-${d.symbol}-${i}`}
                  className="flex items-center gap-2 border-b border-line/40 px-4 py-1.5 text-xs"
                >
                  <span className="w-14 font-mono font-semibold">{d.symbol}</span>
                  <span
                    className="w-16 rounded px-1.5 py-0.5 text-center font-mono text-[10px] uppercase"
                    style={{ backgroundColor: `${color}22`, color }}
                  >
                    {d.action}
                  </span>
                  <span className="truncate text-muted">{d.reason}</span>
                </div>
              );
            })}
            {decisions.data?.length === 0 && (
              <p className="px-4 py-6 text-sm text-muted">No decisions yet.</p>
            )}
          </div>
        </div>
      </div>

      <p className="mt-6 font-mono text-[10px] text-muted">
        Fully autonomous · paper trading only · decisions journaled before execution
      </p>
    </div>
  );
}
