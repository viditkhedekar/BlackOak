"use client";

import Link from "next/link";
import { useState } from "react";
import { useCompanies } from "@/lib/hooks/useCompanies";

export default function ResearchPage() {
  const [query, setQuery] = useState("");
  const { data, isLoading, isError } = useCompanies(query);

  return (
    <div className="mx-auto max-w-4xl">
      <h1 className="mb-1 text-2xl font-semibold">Research</h1>
      <p className="mb-6 text-sm text-muted">
        Search the S&amp;P 500 universe. Deterministic scoring and screening arrive in Phase 2.
      </p>

      <input
        autoFocus
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search by symbol or company name…"
        className="mb-4 w-full rounded-lg border border-line bg-surface px-4 py-2.5 text-sm outline-none placeholder:text-muted focus:border-accent"
      />

      <div className="overflow-hidden rounded-lg border border-line bg-surface">
        <div className="grid grid-cols-[80px_1fr_180px] gap-4 border-b border-line px-4 py-2.5 font-mono text-[10px] uppercase tracking-widest text-muted">
          <span>Symbol</span>
          <span>Name</span>
          <span>Sector</span>
        </div>

        {isLoading && <p className="px-4 py-6 text-sm text-muted">Loading…</p>}
        {isError && <p className="px-4 py-6 text-sm text-negative">Failed to load companies.</p>}
        {data?.items.length === 0 && (
          <p className="px-4 py-6 text-sm text-muted">No matches.</p>
        )}

        {data?.items.map((c) => (
          <Link
            key={c.symbol}
            href={`/company/${c.symbol}`}
            className="grid grid-cols-[80px_1fr_180px] items-center gap-4 border-b border-line/60 px-4 py-3 text-sm last:border-0 hover:bg-line/40"
          >
            <span className="font-mono font-semibold text-accent">{c.symbol}</span>
            <span className="truncate">{c.name}</span>
            <span className="truncate text-xs text-muted">{c.sector ?? "—"}</span>
          </Link>
        ))}
      </div>

      {data && (
        <p className="mt-3 font-mono text-[10px] text-muted">
          {data.total} {data.total === 1 ? "match" : "matches"}
          {data.total > data.items.length ? ` · showing first ${data.items.length}` : ""}
        </p>
      )}
    </div>
  );
}
