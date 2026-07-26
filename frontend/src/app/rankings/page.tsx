"use client";

import Link from "next/link";
import { RegimeBadge } from "@/components/features/RegimeBadge";
import type { RankingRow } from "@/lib/api/client";
import { useRankings, useRegime } from "@/lib/hooks/useCompanies";
import { scoreColor, scoreText } from "@/lib/scoreColor";

const FAMILIES = [
  { key: "valuation", label: "Value" },
  { key: "fundamentals", label: "Fund" },
  { key: "momentum", label: "Mom" },
  { key: "technical", label: "Tech" },
  { key: "risk", label: "Risk" },
] as const;

function Cell({ value }: { value: number | null | undefined }) {
  return (
    <div
      className="rounded px-2 py-1 text-center font-mono text-xs"
      style={{ backgroundColor: scoreColor(value ?? null), color: scoreText(value ?? null) }}
    >
      {value == null ? "—" : Math.round(value)}
    </div>
  );
}

export default function RankingsPage() {
  const { data, isLoading } = useRankings();
  const regime = useRegime();
  const weights = (regime.data?.weights ?? {}) as Record<string, number>;

  return (
    <div className="mx-auto max-w-6xl">
      <div className="mb-1 flex items-end justify-between">
        <h1 className="text-2xl font-semibold">Strategy Rankings</h1>
        <div className="flex items-center gap-2 text-xs text-muted">
          regime <RegimeBadge label={data?.regime} />
        </div>
      </div>
      <p className="mb-4 text-sm text-muted">
        Live composite ranking under the active regime&apos;s family weights. This is what
        the autonomous engine buys from — top decile, composite ≥ 70.
      </p>

      {regime.data?.weights && (
        <div className="mb-4 flex flex-wrap gap-2 font-mono text-[10px] text-muted">
          {FAMILIES.map((f) => (
            <span key={f.key} className="rounded bg-line/40 px-2 py-1">
              {f.label} {Math.round((weights[f.key] ?? 0) * 100)}%
            </span>
          ))}
        </div>
      )}

      <div className="overflow-x-auto rounded-lg border border-line bg-surface">
        <table className="w-full min-w-[720px] text-sm">
          <thead>
            <tr className="border-b border-line font-mono text-[10px] uppercase tracking-wider text-muted">
              <th className="px-3 py-2.5 text-left">#</th>
              <th className="px-3 py-2.5 text-left">Symbol</th>
              <th className="px-3 py-2.5 text-left">Name</th>
              <th className="px-3 py-2.5 text-center">Composite</th>
              {FAMILIES.map((f) => (
                <th key={f.key} className="px-2 py-2.5 text-center">{f.label}</th>
              ))}
              <th className="px-2 py-2.5 text-center">Data</th>
            </tr>
          </thead>
          <tbody>
            {data?.items.map((row: RankingRow) => (
              <tr key={row.symbol} className="border-b border-line/50 hover:bg-line/30">
                <td className="px-3 py-2 font-mono text-xs text-muted">{row.rank}</td>
                <td className="px-3 py-2">
                  <Link
                    href={`/company/${row.symbol}`}
                    className="font-mono font-semibold text-accent hover:underline"
                  >
                    {row.symbol}
                  </Link>
                </td>
                <td className="max-w-[200px] truncate px-3 py-2 text-muted">{row.name}</td>
                <td className="px-3 py-2"><Cell value={row.composite} /></td>
                {FAMILIES.map((f) => (
                  <td key={f.key} className="px-1.5 py-2">
                    <Cell value={(row.families as Record<string, number | null>)[f.key]} />
                  </td>
                ))}
                <td className="px-2 py-2 text-center font-mono text-[10px] text-muted">
                  {Math.round(row.data_completeness * 100)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {isLoading && <p className="px-4 py-6 text-sm text-muted">Loading rankings…</p>}
        {data?.items.length === 0 && (
          <p className="px-4 py-6 text-sm text-muted">
            No strategy scores yet — run the signal pipeline.
          </p>
        )}
      </div>
      {data?.ts && (
        <p className="mt-3 font-mono text-[10px] text-muted">
          as of {new Date(data.ts).toLocaleString()}
        </p>
      )}
    </div>
  );
}
