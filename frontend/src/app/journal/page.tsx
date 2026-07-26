"use client";

import { useState } from "react";
import { RegimeBadge } from "@/components/features/RegimeBadge";
import type { DecisionRow } from "@/lib/api/client";
import { useDecisions } from "@/lib/hooks/useCompanies";

const ACTIONS = ["all", "buy", "sell", "hold", "skip", "blocked"] as const;

const ACTION_COLOR: Record<string, string> = {
  buy: "hsl(140,60%,55%)",
  sell: "hsl(0,65%,60%)",
  hold: "hsl(210,10%,60%)",
  skip: "hsl(45,55%,58%)",
  blocked: "hsl(280,45%,62%)",
};

function evidenceText(evidence: Record<string, unknown>): string {
  const keys = Object.keys(evidence);
  if (keys.length === 0) return "";
  return keys
    .map((k) => `${k}=${JSON.stringify(evidence[k])}`)
    .join("  ");
}

function DecisionItem({ d }: { d: DecisionRow }) {
  const [open, setOpen] = useState(false);
  const color = ACTION_COLOR[d.action] ?? "var(--muted)";
  const hasEvidence = Object.keys(d.evidence as Record<string, unknown>).length > 0;
  return (
    <div className="border-b border-line/50">
      <button
        onClick={() => hasEvidence && setOpen(!open)}
        className="grid w-full grid-cols-[130px_70px_80px_1fr_90px] items-center gap-2 px-3 py-2 text-left text-xs hover:bg-line/30"
      >
        <span className="font-mono text-[10px] text-muted">
          {new Date(d.ts).toLocaleString(undefined, {
            month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
          })}
        </span>
        <span className="font-mono font-semibold">{d.symbol}</span>
        <span
          className="w-fit rounded px-2 py-0.5 font-mono text-[10px] font-semibold uppercase"
          style={{ backgroundColor: `${color}22`, color }}
        >
          {d.action}
        </span>
        <span className="truncate text-muted">{d.reason}</span>
        <span className="text-right font-mono text-[10px] text-muted">
          {hasEvidence ? (open ? "▾ evidence" : "▸ evidence") : ""}
        </span>
      </button>
      {open && hasEvidence && (
        <pre className="overflow-x-auto bg-background/60 px-4 py-2 font-mono text-[10px] text-muted">
          {evidenceText(d.evidence as Record<string, unknown>)}
        </pre>
      )}
    </div>
  );
}

export default function JournalPage() {
  const [action, setAction] = useState<string>("all");
  const { data, isLoading } = useDecisions(
    action === "all" ? undefined : { action },
  );

  const regime = data?.[0]?.regime;

  return (
    <div className="mx-auto max-w-5xl">
      <div className="mb-1 flex items-end justify-between">
        <h1 className="text-2xl font-semibold">Decision Journal</h1>
        {regime && (
          <div className="flex items-center gap-2 text-xs text-muted">
            latest regime <RegimeBadge label={regime} />
          </div>
        )}
      </div>
      <p className="mb-4 text-sm text-muted">
        Every cycle records what the engine did to each candidate — bought, sold, held,
        skipped, or blocked — and why, written before any order is placed. Click a row for
        the evidence.
      </p>

      <div className="mb-4 flex gap-1">
        {ACTIONS.map((a) => (
          <button
            key={a}
            onClick={() => setAction(a)}
            className={`rounded px-3 py-1 font-mono text-xs capitalize ${
              a === action ? "bg-accent text-background" : "text-muted hover:bg-line"
            }`}
          >
            {a}
          </button>
        ))}
      </div>

      <div className="overflow-hidden rounded-lg border border-line bg-surface">
        <div className="grid grid-cols-[130px_70px_80px_1fr_90px] gap-2 border-b border-line bg-line/30 px-3 py-2 font-mono text-[10px] uppercase tracking-wider text-muted">
          <span>Time</span>
          <span>Symbol</span>
          <span>Action</span>
          <span>Reason</span>
          <span />
        </div>
        {data?.map((d, i) => <DecisionItem key={`${d.cycle_id}-${d.symbol}-${i}`} d={d} />)}
        {isLoading && <p className="px-4 py-6 text-sm text-muted">Loading decisions…</p>}
        {data?.length === 0 && (
          <p className="px-4 py-6 text-sm text-muted">
            No decisions recorded yet — the decision engine writes here every cycle.
          </p>
        )}
      </div>
    </div>
  );
}
