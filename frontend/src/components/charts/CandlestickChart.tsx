"use client";

import { CandlestickSeries, ColorType, createChart, CrosshairMode } from "lightweight-charts";
import type { IChartApi, UTCTimestamp } from "lightweight-charts";
import { useEffect, useRef } from "react";
import type { PriceSeries } from "@/lib/api/client";

// Read a CSS custom property so the chart tracks the terminal theme.
function cssVar(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

export function CandlestickChart({ points }: { points: PriceSeries["points"] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const chart = createChart(container, {
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: cssVar("--muted", "#6b7688"),
        fontFamily: "var(--font-geist-mono), monospace",
      },
      grid: {
        vertLines: { color: cssVar("--line", "#1c2433") },
        horzLines: { color: cssVar("--line", "#1c2433") },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: cssVar("--line", "#1c2433") },
      timeScale: { borderColor: cssVar("--line", "#1c2433"), timeVisible: false },
      autoSize: true,
    });
    chartRef.current = chart;

    const series = chart.addSeries(CandlestickSeries, {
      upColor: cssVar("--positive", "#3fb68b"),
      downColor: cssVar("--negative", "#e05c6a"),
      borderVisible: false,
      wickUpColor: cssVar("--positive", "#3fb68b"),
      wickDownColor: cssVar("--negative", "#e05c6a"),
    });

    series.setData(
      points.map((p) => ({
        // lightweight-charts expects a UTC timestamp (seconds) or a business-day string.
        time: (Date.parse(`${p.date}T00:00:00Z`) / 1000) as UTCTimestamp,
        open: Number(p.open),
        high: Number(p.high),
        low: Number(p.low),
        close: Number(p.close),
      })),
    );
    chart.timeScale().fitContent();

    return () => {
      chart.remove();
      chartRef.current = null;
    };
  }, [points]);

  return <div ref={containerRef} className="h-[420px] w-full" />;
}
