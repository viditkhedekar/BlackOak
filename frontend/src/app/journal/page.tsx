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

const num = (v: unknown): string =>
  typeof v === "number" ? v.toFixed(1) : "—";

/** One line answering "why", when the gate fields are present. */
function gateSummary(e: Record<string, unknown>): string | null {
  if (e.composite_percentile === undefined && e.gate_kind === undefined) return null;
  const parts = [
    `score ${num(e.composite_percentile)} / ${num(e.min_composite_percentile)} needed`,
  ];
  if (typeof e.rank === "number") parts.push(`rank ${e.rank} / ${e.rank_threshold}`);
  if (typeof e.weight_covered === "number") {
    parts.push(`coverage ${num((e.weight_covered as number) * 100)}%`);
  }
  if (typeof e.gate_kind === "string" && e.gate_kind) {
    parts.push(e.gate_kind.replace(/_/g, " "));
  }
  return parts.join("  ·  ");
}

/** Which families dragged the composite down, worst first. */
function detractorSummary(e: Record<string, unknown>): string | null {
  const d = e.detractors;
  if (!Array.isArray(d) || d.length === 0) return null;
  return d
    .map((c) => {
      const f = c as Record<string, unknown>;
      return `${f.family} ${num(f.score)} (${num(f.contribution)})`;
    })
    .join("   ");
}

function evidenceText(evidence: Record<string, unknown>): string {
  if (Object.keys(evidence).length === 0) return "";
  return JSON.stringify(evidence, null, 2);
}

function DecisionItem({ d }: { d: DecisionRow }) {
  const [open, setOpen] = useState(false);
  const color = ACTION_COLOR[d.action] ?? "var(--muted)";
  const evidence = d.evidence as Record<string, unknown>;
  const hasEvidence = Object.keys(evidence).length > 0;
  const gate = gateSummary(evidence);
  const detractors = detractorSummary(evidence);
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
        <div className="bg-background/60 px-4 py-2 font-mono text-[10px] text-muted">
          {gate && <div className="pb-1 text-foreground">{gate}</div>}
          {detractors && <div className="pb-1">dragged down by: {detractors}</div>}
          <pre className="overflow-x-auto">
            {evidenceText(d.evidence as Record<string, unknown>)}
          </pre>
        </div>
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
