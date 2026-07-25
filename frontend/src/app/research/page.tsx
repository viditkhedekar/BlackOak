"use client";

import Link from "next/link";
import { useState } from "react";
import { PROFILES, type ScreenerRow } from "@/lib/api/client";
import { useScreener } from "@/lib/hooks/useCompanies";
import { scoreColor, scoreText } from "@/lib/scoreColor";

const CATEGORY_COLUMNS = [
  { key: "financial_health", label: "Health" },
  { key: "growth", label: "Growth" },
  { key: "value", label: "Value" },
  { key: "quality", label: "Quality" },
  { key: "profitability", label: "Profit" },
  { key: "momentum", label: "Mom" },
  { key: "volatility", label: "Vol" },
  { key: "risk", label: "Risk" },
] as const;

const SECTORS = [
  "Information Technology", "Health Care", "Financials", "Consumer Discretionary",
  "Communication Services", "Industrials", "Consumer Staples", "Energy",
  "Utilities", "Real Estate", "Materials",
];

function ScoreCell({ value }: { value: number | null }) {
  return (
    <div
      className="rounded px-2 py-1 text-center font-mono text-xs"
      style={{ backgroundColor: scoreColor(value), color: scoreText(value) }}
    >
      {value == null ? "—" : Math.round(value)}
    </div>
  );
}

export default function ResearchPage() {
  const [profile, setProfile] = useState<string>("balanced");
  const [sector, setSector] = useState<string>("");
  const [sortBy, setSortBy] = useState<string>("composite");
  const [order, setOrder] = useState<"asc" | "desc">("desc");

  const { data, isLoading, isError } = useScreener({
    profile,
    sortBy,
    order,
    sector: sector || undefined,
    minScore: 0.001, // hide never-scored rows
  });

  function toggleSort(key: string) {
    if (sortBy === key) setOrder(order === "desc" ? "asc" : "desc");
    else {
      setSortBy(key);
      setOrder("desc");
    }
  }

  const sortArrow = (key: string) => (sortBy === key ? (order === "desc" ? " ▾" : " ▴") : "");

  return (
    <div className="mx-auto max-w-6xl">
      <div className="mb-1 flex items-end justify-between">
        <h1 className="text-2xl font-semibold">Research Screener</h1>
        <div className="flex gap-1">
          {PROFILES.map((p) => (
            <button
              key={p}
              onClick={() => setProfile(p)}
              className={`rounded px-3 py-1 font-mono text-xs capitalize ${
                p === profile ? "bg-accent text-background" : "text-muted hover:bg-line"
              }`}
            >
              {p}
            </button>
          ))}
        </div>
      </div>
      <p className="mb-4 text-sm text-muted">
        Deterministic 8-category scores, ranked within sector. Click a header to sort; click a
        symbol for the factor-level breakdown.
      </p>

      <select
        value={sector}
        onChange={(e) => setSector(e.target.value)}
        className="mb-4 rounded-lg border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
      >
        <option value="">All sectors</option>
        {SECTORS.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>

      <div className="overflow-x-auto rounded-lg border border-line bg-surface">
        <table className="w-full min-w-[820px] text-sm">
          <thead>
            <tr className="border-b border-line font-mono text-[10px] uppercase tracking-wider text-muted">
              <th className="px-3 py-2.5 text-left">Symbol</th>
              <th className="px-3 py-2.5 text-left">Name</th>
              <th
                className="cursor-pointer px-3 py-2.5 text-center hover:text-foreground"
                onClick={() => toggleSort("composite")}
              >
                Composite{sortArrow("composite")}
              </th>
              {CATEGORY_COLUMNS.map((c) => (
                <th
                  key={c.key}
                  className="cursor-pointer px-2 py-2.5 text-center hover:text-foreground"
                  onClick={() => toggleSort(c.key)}
                >
                  {c.label}
                  {sortArrow(c.key)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data?.items.map((row: ScreenerRow) => (
              <tr key={row.symbol} className="border-b border-line/50 hover:bg-line/30">
                <td className="px-3 py-2">
                  <Link
                    href={`/company/${row.symbol}`}
                    className="font-mono font-semibold text-accent hover:underline"
                  >
                    {row.symbol}
                  </Link>
                </td>
                <td className="max-w-[220px] truncate px-3 py-2 text-muted">{row.name}</td>
                <td className="px-3 py-2">
                  <ScoreCell value={row.composite} />
                </td>
                {CATEGORY_COLUMNS.map((c) => (
                  <td key={c.key} className="px-1.5 py-2">
                    <ScoreCell
                      value={(row.categories as Record<string, number | null>)[c.key]}
                    />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>

        {isLoading && <p className="px-4 py-6 text-sm text-muted">Loading scores…</p>}
        {isError && <p className="px-4 py-6 text-sm text-negative">Failed to load scores.</p>}
        {data?.items.length === 0 && (
          <p className="px-4 py-6 text-sm text-muted">
            No scored companies yet — run the scoring job.
          </p>
        )}
      </div>

      {data?.as_of && (
        <p className="mt-3 font-mono text-[10px] text-muted">
          {data.total} scored · as of {data.as_of} · {profile} profile
        </p>
      )}
    </div>
  );
}
