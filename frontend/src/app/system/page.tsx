"use client";

import { useSystemHealth } from "@/lib/hooks/useCompanies";

const STATUS_COLOR: Record<string, string> = {
  success: "hsl(140,60%,50%)",
  running: "hsl(45,70%,55%)",
  failed: "hsl(0,65%,55%)",
};

export default function SystemHealth() {
  const { data, isLoading } = useSystemHealth();

  return (
    <div className="mx-auto max-w-5xl">
      <h1 className="mb-1 text-2xl font-semibold">System Health</h1>
      <p className="mb-6 text-sm text-muted">
        Pipeline job runs and data-feed freshness — the operational pulse of the autonomous
        system.
      </p>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_260px]">
        <div className="rounded-lg border border-line bg-surface">
          <h2 className="border-b border-line px-4 py-3 font-mono text-xs uppercase tracking-widest text-muted">
            Recent job runs
          </h2>
          <table className="w-full text-sm">
            <tbody>
              {data?.jobs.map((j, i) => {
                const color = STATUS_COLOR[j.status] ?? "var(--muted)";
                return (
                  <tr key={i} className="border-b border-line/40">
                    <td className="px-4 py-2 font-mono text-xs">{j.job_name}</td>
                    <td className="px-2 py-2">
                      <span
                        className="rounded px-2 py-0.5 font-mono text-[10px] uppercase"
                        style={{ backgroundColor: `${color}22`, color }}
                      >
                        {j.status}
                      </span>
                    </td>
                    <td className="px-2 py-2 text-right font-mono text-[10px] text-muted">
                      {j.records_processed ?? 0} recs
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-[10px] text-muted">
                      {new Date(j.started_at).toLocaleString(undefined, {
                        month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
                      })}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {isLoading && <p className="px-4 py-6 text-sm text-muted">Loading…</p>}
          {data?.jobs.length === 0 && (
            <p className="px-4 py-6 text-sm text-muted">No job runs recorded.</p>
          )}
        </div>

        <div className="rounded-lg border border-line bg-surface">
          <h2 className="border-b border-line px-4 py-3 font-mono text-xs uppercase tracking-widest text-muted">
            Feed freshness
          </h2>
          <div className="p-2">
            {data?.feeds.map((f) => (
              <div
                key={f.feed}
                className="flex items-center justify-between px-2 py-1.5 font-mono text-[11px]"
              >
                <span className="text-muted">{f.feed}</span>
                <span>{f.as_of ?? "—"}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
