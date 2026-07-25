# ADR-0001: Monorepo with frontend/ and backend/

**Status:** Accepted · 2026-07-25

## Context
BlackOak has a Next.js frontend and a FastAPI backend whose API contract must stay in lockstep. Separate repos would mean duplicated CI, coordinated releases, and drift between the OpenAPI spec and the TypeScript client generated from it.

## Decision
Single GitHub repository with top-level `frontend/` and `backend/` directories, plus shared `docs/` and one CI pipeline. The frontend consumes only a TypeScript client generated from the backend's OpenAPI spec, so contract drift is a build failure rather than a runtime surprise.

## Consequences
- One PR can change API + client + UI atomically.
- CI must path-filter to avoid rebuilding both stacks on every change (acceptable cost at this scale).
- Deploys remain independent (Vercel for `frontend/`, Railway for `backend/`).
