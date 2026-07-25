"use client";

import ReactECharts from "echarts-for-react";
import type { CompanyScoreDetail } from "@/lib/api/client";

const CATEGORY_LABELS: Record<string, string> = {
  financial_health: "Health",
  growth: "Growth",
  value: "Value",
  quality: "Quality",
  profitability: "Profit",
  momentum: "Momentum",
  volatility: "Volatility",
  risk: "Risk",
};

function cssVar(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

export function ScoreRadar({ categories }: { categories: CompanyScoreDetail["categories"] }) {
  const keys = Object.keys(CATEGORY_LABELS);
  const accent = cssVar("--accent", "#d4a843");
  const line = cssVar("--line", "#1c2433");
  const muted = cssVar("--muted", "#6b7688");

  const option = {
    tooltip: { trigger: "item" },
    radar: {
      indicator: keys.map((k) => ({ name: CATEGORY_LABELS[k], max: 100 })),
      splitNumber: 4,
      axisName: { color: muted, fontSize: 11 },
      splitLine: { lineStyle: { color: line } },
      splitArea: { areaStyle: { color: ["transparent"] } },
      axisLine: { lineStyle: { color: line } },
    },
    series: [
      {
        type: "radar",
        data: [
          {
            // Nulls render as 0 so the shape still closes; the drill-down shows "—".
            value: keys.map((k) => (categories as Record<string, number | null>)[k] ?? 0),
            name: "Score",
            areaStyle: { color: `${accent}44` },
            lineStyle: { color: accent, width: 2 },
            itemStyle: { color: accent },
          },
        ],
      },
    ],
  };

  return <ReactECharts option={option} style={{ height: 320 }} notMerge lazyUpdate />;
}
