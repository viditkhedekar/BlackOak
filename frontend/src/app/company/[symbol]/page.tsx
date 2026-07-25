"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { CandlestickChart } from "@/components/charts/CandlestickChart";
import type { PriceSeries } from "@/lib/api/client";
import { useCompany, usePrices } from "@/lib/hooks/useCompanies";

const RANGES = ["1M", "3M", "6M", "1Y", "2Y", "5Y", "MAX"] as const;

function priceStats(points: PriceSeries["points"]) {
  if (points.length === 0) return null;
  const last = points[points.length - 1];
  const prev = points.length > 1 ? points[points.length - 2] : last;
  const close = Number(last.close);
  const change = close - Number(prev.close);
  const pct = Number(prev.close) !== 0 ? (change / Number(prev.close)) * 100 : 0;
  return { close, change, pct, date: last.date };
}

export default function CompanyPage() {
  const params = useParams<{ symbol: string }>();
  const symbol = (params.symbol ?? "").toUpperCase();
  const [range, setRange] = useState<(typeof RANGES)[number]>("1Y");

  const company = useCompany(symbol);
  const prices = usePrices(symbol, range);
  const stats = prices.data ? priceStats(prices.data.points) : null;
  const up = (stats?.change ?? 0) >= 0;

  return (
    <div className="mx-auto max-w-5xl">
      <Link href="/research" className="mb-4 inline-block text-xs text-muted hover:text-foreground">
        ← Research
      </Link>

      {company.isError ? (
        <p className="text-negative">Unknown symbol: {symbol}</p>
      ) : (
        <>
          <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
            <div>
              <h1 className="font-mono text-2xl font-bold text-accent">{symbol}</h1>
              <p className="text-sm text-muted">{company.data?.name ?? "…"}</p>
              <p className="mt-1 text-xs text-muted">
                {company.data?.sector ?? ""}
                {company.data?.industry ? ` · ${company.data.industry}` : ""}
              </p>
            </div>
            {stats && (
              <div className="text-right">
                <div className="font-mono text-2xl">${stats.close.toFixed(2)}</div>
                <div className={`font-mono text-sm ${up ? "text-positive" : "text-negative"}`}>
                  {up ? "▲" : "▼"} {stats.change.toFixed(2)} ({stats.pct.toFixed(2)}%)
                </div>
                <div className="font-mono text-[10px] text-muted">as of {stats.date}</div>
              </div>
            )}
          </div>

          <div className="rounded-lg border border-line bg-surface p-4">
            <div className="mb-3 flex gap-1">
              {RANGES.map((r) => (
                <button
                  key={r}
                  onClick={() => setRange(r)}
                  className={`rounded px-2.5 py-1 font-mono text-xs ${
                    r === range
                      ? "bg-accent text-background"
                      : "text-muted hover:bg-line hover:text-foreground"
                  }`}
                >
                  {r}
                </button>
              ))}
            </div>

            {prices.isLoading && (
              <div className="flex h-[420px] items-center justify-center text-sm text-muted">
                Loading price history…
              </div>
            )}
            {prices.isError && (
              <div className="flex h-[420px] items-center justify-center text-sm text-negative">
                Failed to load prices.
              </div>
            )}
            {prices.data && prices.data.points.length === 0 && (
              <div className="flex h-[420px] items-center justify-center text-sm text-muted">
                No price data yet — run the backfill for this symbol.
              </div>
            )}
            {prices.data && prices.data.points.length > 0 && (
              <CandlestickChart points={prices.data.points} />
            )}
          </div>
        </>
      )}
    </div>
  );
}
