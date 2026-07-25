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
};
