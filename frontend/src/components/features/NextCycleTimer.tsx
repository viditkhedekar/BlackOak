"use client";

import { useSyncExternalStore } from "react";
import type { ScheduleResponse } from "@/lib/api/client";

const SECOND = 1000;

/* A once-a-second clock living outside React: reading the time is impure, so it cannot
 * happen during render. One interval is shared by every subscriber and stops with the
 * last one. `getSnapshot` stays referentially stable between ticks, which is what
 * useSyncExternalStore requires to avoid re-rendering forever. */
const clock = (() => {
  const listeners = new Set<() => void>();
  let value: number | null = null;
  let timer: ReturnType<typeof setInterval> | null = null;

  return {
    subscribe(onChange: () => void): () => void {
      listeners.add(onChange);
      if (timer === null) {
        // React re-reads the snapshot right after subscribing, so seeding it here is
        // picked up immediately rather than after the first tick.
        value = Date.now();
        timer = setInterval(() => {
          value = Date.now();
          for (const listener of listeners) listener();
        }, SECOND);
      }
      return () => {
        listeners.delete(onChange);
        if (listeners.size === 0 && timer !== null) {
          clearInterval(timer);
          timer = null;
        }
      };
    },
    getSnapshot: (): number | null => value,
    getServerSnapshot: (): number | null => null,
  };
})();

/** Current time, or null before mount so server and client render the same thing. */
function useNow(): number | null {
  return useSyncExternalStore(clock.subscribe, clock.getSnapshot, clock.getServerSnapshot);
}

function formatRemaining(ms: number): string {
  const total = Math.max(0, Math.floor(ms / SECOND));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h}h ${String(m).padStart(2, "0")}m`;
  if (m > 0) return `${m}m ${String(s).padStart(2, "0")}s`;
  return `${s}s`;
}

/** The target time as the desk reads it — always ET, regardless of where the browser is. */
function etLabel(iso: string, serverNow: number): string {
  const target = new Date(iso);
  const time = target.toLocaleTimeString("en-US", {
    timeZone: "America/New_York",
    hour: "numeric",
    minute: "2-digit",
    hour12: false,
  });
  const dayOf = (d: Date) =>
    d.toLocaleDateString("en-US", { timeZone: "America/New_York", weekday: "short" });
  const sameDay =
    target.toLocaleDateString("en-US", { timeZone: "America/New_York" }) ===
    new Date(serverNow).toLocaleDateString("en-US", { timeZone: "America/New_York" });
  return sameDay ? `${time} ET` : `${dayOf(target)} ${time} ET`;
}

export function NextCycleTimer({
  data,
  dataUpdatedAt,
}: {
  data: ScheduleResponse;
  dataUpdatedAt: number;
}) {
  const now = useNow();

  // Count against the API's clock. dataUpdatedAt is the browser time this payload landed,
  // so the difference is the skew between the two machines.
  const skew = data.server_time ? Date.parse(data.server_time) - dataUpdatedAt : 0;
  const serverNow = (now ?? dataUpdatedAt) + skew;

  const target = data.next_cycle_at ? Date.parse(data.next_cycle_at) : null;
  const remaining = target != null ? target - serverNow : null;

  const workerDown = !data.worker_running;
  const firing = remaining != null && remaining <= 0;

  let value: string;
  let tone = "var(--accent)";
  if (target == null) {
    value = "—";
    tone = "var(--muted)";
  } else if (firing) {
    value = "running…";
  } else {
    value = formatRemaining(remaining as number);
  }
  // A countdown with no worker behind it is a promise nothing will keep.
  if (workerDown && !firing) tone = "var(--muted)";

  const sub = (() => {
    if (target == null) return "no session scheduled";
    if (workerDown) {
      return data.market_hours
        ? "worker not running — no trades will fire"
        : `worker idle · next ${etLabel(data.next_cycle_at as string, serverNow)}`;
    }
    if (firing) return "cycle in progress";
    return `${etLabel(data.next_cycle_at as string, serverNow)} · every ${data.interval_minutes}m`;
  })();

  return (
    <div className="rounded-lg border border-line bg-surface p-4">
      <div className="flex items-center gap-1.5">
        <span className="font-mono text-[10px] uppercase tracking-widest text-muted">
          Next trades
        </span>
        <span
          className="h-1.5 w-1.5 rounded-full"
          style={{
            backgroundColor: workerDown ? "var(--muted)" : "var(--positive)",
            boxShadow: workerDown ? "none" : "0 0 0 2px color-mix(in srgb, var(--positive) 20%, transparent)",
          }}
          aria-hidden
        />
      </div>
      <div className="mt-1 text-xl font-semibold tabular-nums" style={{ color: tone }}>
        {now == null && target != null && !firing ? "—" : value}
      </div>
      <div
        className="font-mono text-[10px]"
        style={{
          color:
            workerDown && data.market_hours ? "var(--negative)" : "var(--muted)",
        }}
      >
        {sub}
      </div>
    </div>
  );
}
