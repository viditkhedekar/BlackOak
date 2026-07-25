# ADR-0002: Clerk for authentication

**Status:** Accepted · 2026-07-25

## Context
We need hosted auth that works cleanly across a Next.js frontend and a FastAPI backend. Candidates: Clerk, Supabase Auth, roll-your-own.

## Decision
Clerk. Its Next.js components give a polished sign-in experience with minimal code, and the backend verifies its JWTs statelessly via JWKS in a single FastAPI dependency (`get_current_user`). A Clerk webhook (svix-verified) mirrors identities into our `users` table so all domain data is keyed by our own UUIDs, not Clerk IDs.

## Consequences
- Vendor lock-in is contained: only the JWT-verification dependency and the webhook handler know about Clerk; swapping providers would not touch domain or service code.
- No passwords or sessions stored on our side.
- Supabase Auth remains a viable fallback if Clerk pricing/limits become a problem.
