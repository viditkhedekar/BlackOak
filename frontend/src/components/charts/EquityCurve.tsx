"use client";

import ReactECharts from "echarts-for-react";
import { useState } from "react";
import type { PerformanceResponse } from "@/lib/api/client";

// Portfolio wears the terminal accent; SPY is the cool reference line. The pair clears
// CVD separation (ΔE 23.8 protan) against the --surface, so the two series stay legible
// without relying on the legend alone.
const PORTFOLIO = "#d4a843";
const BENCHMARK = "#4f8ecc";
const AXIS = "#6b7688";
const GRID_LINE = "#1c2433";

type Mode = "value" | "indexed";

function usd(v: number, digits = 0): string {
  return `$${v.toLocaleString(undefined, { maximumFractionDigits: digits })}`;
}

function pct(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${(v * 100).toFixed(2)}%`;
}

/** Rebase a series to 100 at its first point so two different scales share one axis. */
function indexTo100(values: number[]): (number | null)[] {
  const base = values.find((v) => v > 0);
  if (!base) return values.map(() => null);
  return values.map((v) => Number(((v / base) * 100).toFixed(3)));
}

/** Pair each value with its timestamp for the time axis; nulls stay as gaps. */
function atTimes(times: number[], values: (number | null)[]): [number, number | null][] {
  return times.map((t, i) => [t, values[i] ?? null]);
}

const DAY_MS = 86_400_000;

function stamp(ms: number, withTime: boolean): string {
  const d = new Date(ms);
  const day = d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  if (!withTime) return day;
  return `${day} ${d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}`;
}

export function EquityCurve({ data }: { data: PerformanceResponse }) {
  const [mode, setMode] = useState<Mode>("value");

  const points = data.points ?? [];
  const times = points.map((p) => new Date(p.ts).getTime());
  const equity = points.map((p) => p.equity);
  const spy = data.spy ?? [];
  // Require real closes, not just a matching length — a benchmark that failed to resolve
  // comes back as zeros, and an all-zero overlay is worse than no overlay.
  const hasBenchmark =
    spy.length === points.length && spy.length > 0 && spy.some((v) => v > 0);

  const latest = equity.length ? equity[equity.length - 1] : null;
  const totalReturn = data.total_return;
  const spyReturn = data.spy_return;
  const excess =
    totalReturn != null && spyReturn != null ? totalReturn - spyReturn : null;

  const indexed = mode === "indexed" && hasBenchmark;

  // A line through one or two snapshots draws nothing you can see, so the early points
  // carry visible markers until there are enough of them to read as a curve.
  const sparse = points.length < 3;
  const marker = { showSymbol: sparse, symbolSize: 8 } as const;
  // Snapshots land every 15 minutes, so a single session's worth of points all share a
  // date. Times only earn their place on the axis while the whole curve fits in a few days.
  const span = times.length > 1 ? times[times.length - 1] - times[0] : 0;
  const intraday = span > 0 && span < 5 * DAY_MS;

  const series = indexed
    ? [
        {
          name: "Portfolio",
          type: "line",
          data: atTimes(times, indexTo100(equity)),
          ...marker,
          lineStyle: { color: PORTFOLIO, width: 2 },
          itemStyle: { color: PORTFOLIO },
        },
        {
          name: "SPY",
          type: "line",
          data: atTimes(times, indexTo100(spy)),
          ...marker,
          lineStyle: { color: BENCHMARK, width: 2 },
          itemStyle: { color: BENCHMARK },
        },
      ]
    : [
        {
          name: "Portfolio",
          type: "line",
          data: atTimes(times, equity),
          ...marker,
          lineStyle: { color: PORTFOLIO, width: 2 },
          itemStyle: { color: PORTFOLIO },
          areaStyle: { color: `${PORTFOLIO}22` },
        },
      ];

  const option = {
    grid: { left: 64, right: 20, top: indexed ? 34 : 20, bottom: 40 },
    // Crosshair + shared tooltip: an equity curve is read by hovering, not by squinting.
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "line", lineStyle: { color: AXIS } },
      backgroundColor: "#10151f",
      borderColor: GRID_LINE,
      textStyle: { color: "#d7dde8", fontSize: 11 },
      formatter: (params: Array<{ axisValue: number; seriesName: string; value: [number, number | null]; color: string }>) => {
        // Always time-stamped in the tooltip: at 15-minute density the date alone cannot
        // tell you which of the day's marks you are hovering.
        const at = params[0]?.axisValue;
        const head = `<div style="color:${AXIS};font-size:10px">${at ? stamp(at, true) : ""}</div>`;
        const rows = params
          .map((p) => {
            const raw = p.value?.[1];
            const v =
              raw == null
                ? "—"
                : indexed
                  ? raw.toFixed(2)
                  : usd(raw, 2);
            return `<div><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${p.color};margin-right:6px"></span>${p.seriesName} <b>${v}</b></div>`;
          })
          .join("");
        return head + rows;
      },
    },
    // A legend is mandatory once two series share the plot; a lone series is named by the title.
    legend: indexed
      ? {
          data: ["Portfolio", "SPY"],
          top: 0,
          right: 0,
          icon: "roundRect",
          itemWidth: 10,
          itemHeight: 2,
          textStyle: { color: AXIS, fontSize: 10 },
        }
      : undefined,
    // A real time axis, not a category one: snapshots are irregular (15 min in session,
    // then a 17-hour hole overnight) and a category axis would space every gap equally,
    // drawing a flat overnight stretch as if it were a trading day.
    xAxis: {
      type: "time",
      axisLabel: {
        color: AXIS,
        fontSize: 10,
        formatter: (v: number) => stamp(v, intraday),
        hideOverlap: true,
      },
      axisLine: { lineStyle: { color: GRID_LINE } },
    },
    yAxis: {
      type: "value",
      scale: true, // equity curves read as change, so the baseline is not pinned to zero
      axisLabel: {
        color: AXIS,
        fontSize: 10,
        formatter: (v: number) => (indexed ? v.toFixed(0) : usd(v)),
      },
      splitLine: { lineStyle: { color: GRID_LINE } },
    },
    series,
  };

  return (
    <div>
      <div className="flex items-end justify-between gap-4 px-4 py-3">
        <div>
          <div className="font-mono text-[10px] uppercase tracking-widest text-muted">
            Portfolio value
          </div>
          <div className="mt-0.5 flex items-baseline gap-2">
            <span className="text-2xl font-semibold tabular-nums">
              {latest != null ? usd(latest) : "—"}
            </span>
            {totalReturn != null && (
              <span
                className="font-mono text-xs tabular-nums"
                style={{ color: totalReturn >= 0 ? "var(--positive)" : "var(--negative)" }}
              >
                {pct(totalReturn)}
              </span>
            )}
          </div>
          {points.length < 2 ? (
            <div className="font-mono text-[10px] text-muted">
              {points.length} snapshot · the curve marks equity every 15 min in session
            </div>
          ) : (
            excess != null && (
              <div className="font-mono text-[10px] text-muted">
                SPY {pct(spyReturn)} · {excess >= 0 ? "ahead by" : "behind by"}{" "}
                {pct(Math.abs(excess))}
              </div>
            )
          )}
        </div>

        {hasBenchmark && (
          <div className="flex gap-1">
            {(["value", "indexed"] as const).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={`rounded px-2.5 py-1 font-mono text-[10px] ${
                  m === mode ? "bg-accent text-background" : "text-muted hover:bg-line"
                }`}
              >
                {m === "value" ? "Value" : "vs SPY"}
              </button>
            ))}
          </div>
        )}
      </div>

      <ReactECharts option={option} style={{ height: 280 }} notMerge />
    </div>
  );
}
