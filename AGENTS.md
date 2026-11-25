# glassdesk — Agent Guide

glassdesk is a knowledge assistant app delivered per enterprise customer (one deployment per
customer). A FastAPI backend runs a lite-agent `Agent` whose tools call llm-steward over its
Python SDK; a React SPA shows chat, citations and the agent's live timeline.

## Sources of truth

1. `docs/glassdesk-design.md` — the design (§10 stage plan). A change that contradicts it updates it.
2. Plans in `docs/superpowers/plans/`, one per stage group.

## Layout

```
backend/   FastAPI app, agent, steward port, timeline projection (Python 3.12, uv)
frontend/  React + Vite + TypeScript SPA (pnpm)
docs/      design and plans
```

## Rules

1. Never import `llm_steward`; only `llm_steward_client.AsyncSteward` over HTTP.
2. Every LLM call goes through a lite-model role (`desk.answer`); no model id in code.
3. Agent tools only read or propose: no tool writes a KB entry itself. A proposal is a steward
   suggestion, and steward's policy decides whether it goes live (low risk may), waits for the user or for review.
4. The timeline never exposes the system prompt, provenance URLs, keys or upstream error text.
5. Tests never call a real LLM, a real steward, Ollama or llm-gateway (`AsyncFakeModel`, `FakeSteward`).
6. Unknown cost is `null` in the API and "未知" in the UI, never 0.
7. Code-facing text English; UI copy Chinese; Conventional Commits.

## Commands

Backend (`backend/`): `uv run ruff check && uv run ruff format --check && uv run mypy && uv run pytest`
(PG tests need `GLASSDESK_TEST_DATABASE_URL`).
Frontend (`frontend/`): `pnpm typecheck && pnpm lint && pnpm test && pnpm build`; `pnpm e2e`.

## Ports

backend `127.0.0.1:8740`, frontend dev `8741`, e2e preview `8742`, e2e backend (fake mode) `8743`.

## Current stage

First real deployment (2026-11-26): `bootstrap.sh` verified from zero on the host's Ollama, every flow walked in a
browser; fixes in design §12 "首次真实部署". Two steward keys: `GLASSDESK_STEWARD_API_KEY` (read, write) for
everything people do, `GLASSDESK_STEWARD_REVIEW_KEY` (read, write, review) for reviewing only.
G4 (2026-11-25): delivery — branding, demo seed, image, `deploy/` (compose, bootstrap, 部署文档).
G0–G3 done and merged 2026-11-25. Deploy: `deploy/README.md`.
