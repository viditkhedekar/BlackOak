"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";

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
