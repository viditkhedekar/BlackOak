import type { paths } from "./api-types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type JSON200<P extends keyof paths, M extends "get"> = paths[P][M] extends {
  responses: { 200: { content: { "application/json": infer R } } };
}
  ? R
  : never;

export type HealthResponse = JSON200<"/api/v1/health", "get">;
export type CompanyList = JSON200<"/api/v1/companies", "get">;
export type CompanySummary = CompanyList["items"][number];
export type CompanyDetail = JSON200<"/api/v1/companies/{symbol}", "get">;
export type PriceSeries = JSON200<"/api/v1/companies/{symbol}/prices", "get">;
export type ScreenerResponse = JSON200<"/api/v1/screener", "get">;
export type ScreenerRow = ScreenerResponse["items"][number];
export type CompanyScoreDetail = JSON200<"/api/v1/companies/{symbol}/scores", "get">;

export type RankingsResponse = JSON200<"/api/v1/strategy/rankings", "get">;
export type RankingRow = RankingsResponse["items"][number];
export type RegimeResponse = JSON200<"/api/v1/strategy/regime", "get">;
export type DecisionRow = JSON200<"/api/v1/strategy/decisions", "get">[number];
export type PortfolioResponse = JSON200<"/api/v1/portfolio", "get">;
export type PerformanceResponse = JSON200<"/api/v1/performance", "get">;
export type BacktestSummary = JSON200<"/api/v1/backtests", "get">[number];
export type BacktestDetail = JSON200<"/api/v1/backtests/{run_id}", "get">;
export type SystemHealth = JSON200<"/api/v1/system/health", "get">;

export const PROFILES = ["conservative", "balanced", "aggressive"] as const;
export type Profile = (typeof PROFILES)[number];

export interface ScreenerParams {
  profile: string;
  sortBy: string;
  order: "asc" | "desc";
  sector?: string;
  minScore?: number;
}

async function get<T>(path: string, params?: Record<string, string>): Promise<T> {
  const url = new URL(`${API_URL}${path}`);
  if (params) {
    for (const [k, v] of Object.entries(params)) url.searchParams.set(k, v);
  }
  const res = await fetch(url, { headers: { Accept: "application/json" } });
  if (!res.ok) {
    throw new Error(`API ${path} failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => get<HealthResponse>("/api/v1/health"),
  companies: (query?: string) =>
    get<CompanyList>("/api/v1/companies", query ? { query } : undefined),
  company: (symbol: string) => get<CompanyDetail>(`/api/v1/companies/${symbol}`),
  prices: (symbol: string, range: string) =>
    get<PriceSeries>(`/api/v1/companies/${symbol}/prices`, { range }),
  screener: (p: ScreenerParams) => {
    const params: Record<string, string> = {
      profile: p.profile,
      sortBy: p.sortBy,
      order: p.order,
      limit: "100",
    };
    if (p.sector) params.sector = p.sector;
    if (p.minScore != null) params.minScore = String(p.minScore);
    return get<ScreenerResponse>("/api/v1/screener", params);
  },
  scores: (symbol: string, profile: string) =>
    get<CompanyScoreDetail>(`/api/v1/companies/${symbol}/scores`, { profile }),
  rankings: () => get<RankingsResponse>("/api/v1/strategy/rankings", { limit: "60" }),
  regime: () => get<RegimeResponse>("/api/v1/strategy/regime"),
  decisions: (params?: { action?: string; symbol?: string }) => {
    const p: Record<string, string> = { limit: "150" };
    if (params?.action) p.action = params.action;
    if (params?.symbol) p.symbol = params.symbol;
    return get<DecisionRow[]>("/api/v1/strategy/decisions", p);
  },
  portfolio: () => get<PortfolioResponse>("/api/v1/portfolio"),
  performance: () => get<PerformanceResponse>("/api/v1/performance"),
  backtests: () => get<BacktestSummary[]>("/api/v1/backtests"),
  backtest: (id: string) => get<BacktestDetail>(`/api/v1/backtests/${id}`),
  systemHealth: () => get<SystemHealth>("/api/v1/system/health"),
};
