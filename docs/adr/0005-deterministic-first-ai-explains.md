# ADR-0005: Deterministic engine decides; AI only explains

**Status:** Accepted · 2026-07-25

## Context
An "AI stock picker" that lets an LLM choose trades is unauditable, unreproducible, and unconvincing as an engineering showcase. LLMs are, however, excellent at synthesizing structured data into readable analysis.

## Decision
Portfolio decisions come exclusively from the deterministic pipeline: factor scores (sector-relative percentiles with every raw input stored in `research_scores.inputs`) → constraint-based optimizer → rule-based rebalance triggers. The AI layer (multi-agent research desk on the Claude API, temperature 0, structured outputs) generates theses and narratives *about* those decisions. Hard rules:
1. AI output never mutates a score and never triggers a trade.
2. Every AI claim must carry a `data_ref` to a metric we passed in; prompts forbid outside knowledge.
3. Agent disagreement is surfaced (a "Contested" label with both cases), not averaged away.

## Consequences
- Every allocation is reproducible from stored inputs; golden-file tests lock the engines.
- The pipeline survives LLM outages — analytics and trading are unaffected.
- AI cost is bounded (regeneration only on material change, per-run token budget).
- v2 optimizer modes (MVO/HRP) can be A/B'd against the deterministic engine because both are deterministic.
