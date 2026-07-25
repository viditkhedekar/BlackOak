"use client";

import { useState } from "react";
import { ScoreRadar } from "@/components/charts/ScoreRadar";
import { PROFILES } from "@/lib/api/client";
import { useScores } from "@/lib/hooks/useCompanies";
import { scoreColor, scoreText } from "@/lib/scoreColor";

const CATEGORY_LABELS: Record<string, string> = {
  financial_health: "Financial Health",
  growth: "Growth",
  value: "Value",
  quality: "Quality",
  profitability: "Profitability",
  momentum: "Momentum",
  volatility: "Volatility",
  risk: "Risk",
};

function fmtRaw(raw: number | null): string {
  if (raw == null) return "—";
  if (Math.abs(raw) >= 1000) return raw.toLocaleString(undefined, { maximumFractionDigits: 0 });
  return raw.toFixed(Math.abs(raw) < 1 ? 3 : 2);
}

export function ScorePanel({ symbol }: { symbol: string }) {
  const [profile, setProfile] = useState<string>("balanced");
  const { data, isLoading, isError } = useScores(symbol, profile);

  return (
    <div className="mt-6 rounded-lg border border-line bg-surface p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-mono text-xs uppercase tracking-widest text-muted">
            Research Score
          </h2>
          {data && (
            <p className="mt-1 text-sm">
              Composite{" "}
              <span
                className="rounded px-2 py-0.5 font-mono font-semibold"
                style={{ backgroundColor: scoreColor(data.composite), color: scoreText(data.composite) }}
              >
                {data.composite == null ? "—" : Math.round(data.composite)}
              </span>{" "}
              <span className="text-muted">
                · {Math.round((data.data_completeness ?? 0) * 100)}% data · engine{" "}
                {data.engine_version}
              </span>
            </p>
          )}
        </div>
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

      {isLoading && <p className="py-8 text-center text-sm text-muted">Loading scores…</p>}
      {isError && (
        <p className="py-8 text-center text-sm text-muted">
          No scores yet for {symbol}. Run the scoring job once this symbol has prices and
          fundamentals.
        </p>
      )}

      {data && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[360px_1fr]">
          <ScoreRadar categories={data.categories} />

          <div className="overflow-hidden rounded border border-line">
            <div className="grid grid-cols-[1fr_90px_70px_90px] gap-2 border-b border-line bg-line/30 px-3 py-2 font-mono text-[10px] uppercase tracking-wider text-muted">
              <span>Factor</span>
              <span className="text-right">Raw</span>
              <span className="text-center">Dir</span>
              <span className="text-right">Score</span>
            </div>
            {data.breakdown.map((cat) => (
              <div key={cat.category}>
                <div className="flex items-center justify-between bg-background/40 px-3 py-1.5">
                  <span className="text-xs font-semibold">{CATEGORY_LABELS[cat.category]}</span>
                  <span
                    className="rounded px-2 py-0.5 font-mono text-[11px]"
                    style={{ backgroundColor: scoreColor(cat.score), color: scoreText(cat.score) }}
                  >
                    {cat.score == null ? "—" : Math.round(cat.score)}
                  </span>
                </div>
                {cat.factors.map((f) => (
                  <div
                    key={f.factor}
                    className="grid grid-cols-[1fr_90px_70px_90px] gap-2 px-3 py-1 text-xs"
                  >
                    <span className="truncate text-muted">{f.factor}</span>
                    <span className="text-right font-mono">{fmtRaw(f.raw)}</span>
                    <span className="text-center font-mono text-[10px] text-muted">
                      {f.inverse ? "inv" : "dir"}
                    </span>
                    <span
                      className="rounded text-right font-mono"
                      style={{ color: scoreText(f.score) }}
                    >
                      {f.score == null ? "—" : Math.round(f.score)}
                    </span>
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
