# glassdesk G3 Implementation Plan — insights and feedback

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (inline, as G1/G2).

**Goal:** Users rate each answer (有帮助 / 没帮助); the rating is kept per answer in glassdesk and passed to steward for every item the answer cited, so steward's review flags work. Reviewers and admins get an insights page: answers per day, failures, tokens and cost (unknown cost never shown as 0), helpful rate, the KB's gaps and counts from steward.

**Spec:** `docs/glassdesk-design.md` §4 (洞察), §5 "Admin data and audit" (insights via the admin token; answer feedback), §10 G3. KB `global/engineering/dates-time-and-metrics.md` §4, §6.

## Global Constraints

- Unknown is not zero: a run whose endpoint reported no cost is left out of the cost sum and counted apart (`cost_unknown_runs`); all unknown → `cost_usd: null` ("未知"). Unrated answers leave the helpful-rate denominator; none rated → `null` ("—").
- Days are calendar days in `GLASSDESK_TIMEZONE` (default `Asia/Shanghai`); stored instants are `timestamptz`.
- steward's admin API needs `GLASSDESK_STEWARD_ADMIN_TOKEN` and `GLASSDESK_STEWARD_NAMESPACE`; without them the KB part of insights is `null` ("未配置"), the rest still works. The token never reaches the browser.
- Insights: role reviewer or admin (403 for member). Feedback: the conversation's owner only (404 otherwise).
- Fake mode labels its steward numbers as demo data (`demo: true` → "演示数据").
- Feedback to steward is best effort: a steward failure never fails the rating.

## Review Focus

1. Rating the same answer twice (change of mind) → one row, latest value; steward told again. Test Task 1.
2. Rating someone else's answer, or a run id not in this conversation → 404. Test Task 1.
3. A day with runs whose cost is unknown and others known → known sum, unknown count; no run → the day still listed with zeros for counts and `null` cost. Test Task 2.
4. A run finishing near midnight UTC lands on the deployment's local day. Test Task 2.
5. steward admin API down or unconfigured → insights still answer with `kb: null`. Test Task 2.

### Task 1: Usage and feedback (backend)
- Migration 0006: `run_usage(run_id pk, conversation_id, user_id, finished_at timestamptz, input_tokens, output_tokens, cost_usd numeric null, failed bool)`, `answer_feedback(run_id, user_id, helpful, updated_at, pk(run_id,user_id))`, `run_passages.retrieval_id text`.
- `on_passages(call_id, retrieval_id, numbered)`; `work()` writes `run_usage` from `RunResult.usage` after every run (also failed).
- `POST /api/conversations/{id}/answers/{run_id}/feedback {helpful}` → upsert, then `StewardPort.feedback(retrieval_id, item_id, helpful)` for each cited item (logged on failure). `Answer.feedback: bool | None` (the viewer's rating).
- Tests: change of mind keeps one row; steward sees one feedback per cited item each time; another user's conversation → 404; unknown run → 404; steward down → 200.

### Task 2: Insights (backend)
- `StewardPort.stats() -> KbStats | None` over `/admin/v1/ns/{slug}/stats` (bearer admin token; own small httpx client); `None` when not configured or unreachable. FakeSteward returns fixed numbers with `demo=True`.
- `GET /api/insights` (reviewer/admin) → `{days: [{day, answers, failed, tokens, cost_usd, cost_unknown_runs}] (7, oldest first), totals {...}, helpful_rate, rated, kb: {entries_by_status, pending_reviews, awaiting_user, gaps:[{query,count}]} | null, demo}`.
- Tests: mixed known/unknown cost; empty day; local-day bucketing; member 403; steward stats down → `kb: null`.

### Task 3: Frontend
- Answer footer: `有帮助` / `没帮助` (pressed state from `feedback`), posting and updating the cache.
- `/insights`: KPI tiles (回答数, 失败, tokens, 成本 with "N 次未知" / "未知", 好评率 or "—"), 7-day table, KB block (gaps list, counts) or "未配置", "演示数据" badge; members see "需要审核权限".
- Tests for each of those strings.

### Task 4: e2e + close-out
- e2e: ask → 有帮助 → insights shows ≥1 answer, 好评率 100% for a fresh e2e conversation is not stable across reruns, so assert the tile renders a percentage and the gaps list shows the fake's gap.
- Close-out as G2.
