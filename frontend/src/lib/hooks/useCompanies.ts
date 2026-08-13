"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api, type ScreenerParams } from "@/lib/api/client";

export function useScreener(params: ScreenerParams) {
  return useQuery({
    queryKey: ["screener", params],
    queryFn: () => api.screener(params),
    placeholderData: keepPreviousData,
  });
}

// Dashboard hooks — poll live surfaces every 15s.
const LIVE = { refetchInterval: 15_000, placeholderData: keepPreviousData } as const;

export function useRankings() {
  return useQuery({ queryKey: ["rankings"], queryFn: () => api.rankings(), ...LIVE });
}
export function useRegime() {
  return useQuery({ queryKey: ["regime"], queryFn: () => api.regime(), ...LIVE });
}
export function useDecisions(params?: { action?: string; symbol?: string }) {
  return useQuery({
    queryKey: ["decisions", params],
    queryFn: () => api.decisions(params),
    ...LIVE,
  });
}
export function usePortfolio() {
  return useQuery({ queryKey: ["portfolio"], queryFn: () => api.portfolio(), ...LIVE });
}
export function usePerformance() {
  return useQuery({ queryKey: ["performance"], queryFn: () => api.performance(), ...LIVE });
}
export function useSchedule() {
  return useQuery({ queryKey: ["schedule"], queryFn: () => api.schedule(), ...LIVE });
}
export function useBacktests() {
  return useQuery({ queryKey: ["backtests"], queryFn: () => api.backtests() });
}
export function useBacktest(id: string) {
  return useQuery({
    queryKey: ["backtest", id],
    queryFn: () => api.backtest(id),
    enabled: Boolean(id),
  });
}
export function useSystemHealth() {
  return useQuery({ queryKey: ["systemHealth"], queryFn: () => api.systemHealth(), ...LIVE });
}

export function useScores(symbol: string, profile: string) {
  return useQuery({
    queryKey: ["scores", symbol, profile],
    queryFn: () => api.scores(symbol, profile),
    enabled: Boolean(symbol),
    retry: false,
  });
}

export function useCompanies(query: string) {
  return useQuery({
    queryKey: ["companies", query],
    queryFn: () => api.companies(query || undefined),
    placeholderData: keepPreviousData,
  });
}

export function useCompany(symbol: string) {
  return useQuery({
    queryKey: ["company", symbol],
    queryFn: () => api.company(symbol),
    enabled: Boolean(symbol),
  });
}

export function usePrices(symbol: string, range: string) {
  return useQuery({
    queryKey: ["prices", symbol, range],
    queryFn: () => api.prices(symbol, range),
    enabled: Boolean(symbol),
  });
}
