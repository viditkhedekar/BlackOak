"use client";

import { useHealth } from "@/lib/hooks/useHealth";

function StatusDot({ ok }: { ok: boolean | undefined }) {
  const color = ok === undefined ? "bg-muted" : ok ? "bg-positive" : "bg-negative";
  return <span className={`inline-block h-2.5 w-2.5 rounded-full ${color}`} />;
}

export default function Dashboard() {
  const { data, isLoading, isError, dataUpdatedAt } = useHealth();

  const apiOk = isError ? false : data ? data.status === "ok" : undefined;
  const dbOk = isError ? false : data ? data.db === "ok" : undefined;

  return (
    <div className="mx-auto max-w-4xl">
      <h1 className="mb-1 text-2xl font-semibold">Dashboard</h1>
      <p className="mb-8 text-sm text-muted">
        Phase 0 — walking skeleton. Market data, scoring, and portfolio views arrive in later
        phases.
      </p>

      <div className="rounded-lg border border-line bg-surface p-6">
        <h2 className="mb-4 font-mono text-xs uppercase tracking-widest text-muted">
          System status
        </h2>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div className="flex items-center gap-3">
            <StatusDot ok={apiOk} />
            <div>
              <div className="text-sm">API</div>
              <div className="font-mono text-xs text-muted">
                {isLoading ? "checking…" : apiOk ? "operational" : "unreachable"}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <StatusDot ok={dbOk} />
            <div>
              <div className="text-sm">Database</div>
              <div className="font-mono text-xs text-muted">
                {isLoading ? "checking…" : dbOk ? "operational" : (data?.db ?? "unreachable")}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <StatusDot ok={data !== undefined} />
            <div>
              <div className="text-sm">Environment</div>
              <div className="font-mono text-xs text-muted">{data?.environment ?? "unknown"}</div>
            </div>
          </div>
        </div>
        {dataUpdatedAt > 0 && (
          <p className="mt-4 font-mono text-[10px] text-muted">
            last checked {new Date(dataUpdatedAt).toLocaleTimeString()}
          </p>
        )}
      </div>
    </div>
  );
}
