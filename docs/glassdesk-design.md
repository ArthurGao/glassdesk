# glassdesk design: a knowledge assistant whose process is visible

2026-11-25 · Status: draft, awaiting owner approval

## 1. Intent

**glassdesk** is a knowledge-assistant app that is **demonstrated or delivered** to one enterprise customer: the
customer's employees ask the agent questions, the agent looks for answers in the governed knowledge base (KB) and in
memory, and every sentence of the answer carries its source. New knowledge that comes up in a conversation enters the
KB under the governance rules (automatically / by asking the user / by expert review), or can be entered by hand.
Its selling point is a **visible process** (glass box): for every answer the customer can see on the page what the
agent did — which tools it called, which passages it found, how much money and time it spent.

It is also the **first end-user app** of the lite-ai stack: it uses a real app to connect lite-agent, llm-steward
(and the lite-rag / lite-mem behind it) and lite-model, and to expose problems in the modules' interfaces (known gaps:
token streaming, cross-module tracing).

### Goals

- One deployment per customer (docker compose), which can be demonstrated live in front of the customer and also
  delivered for the customer to run themselves.
- Chat: answers carry citations; every step of the agent is pushed to the page in real time (step-level streaming).
- Execution page: for any answer, the full timeline can be expanded (tool calls, retrieval results, model calls,
  tokens / cost / duration).
- Three ways for knowledge to enter the KB: AI decides automatically (low-risk items take effect automatically), ask
  the user (confirmation card), manual entry (an entry or an uploaded document).
- The 知识库 (Knowledge base) page: documents, entries and their status, candidates awaiting confirmation / review,
  and "KB 缺什么" ("what the KB lacks").
- Rebrandable (customer name, logo, main colour), with a replaceable model endpoint (the customer's own Ollama /
  OpenAI-compatible / LiteLLM).

### Non-goals (not in v1)

- Multi-tenant SaaS, public sign-up, billing. One deployment serves one customer only.
- Implementing RAG, memory or governance itself: all of it goes to llm-steward (which hands it on to lite-rag /
  lite-mem / WeKnora).
- Token-level streaming: lite-model does not do streaming at present (`lite-model/docs/lite-model-design.md:46`), so
  v1 only does step-level streaming; token streaming is a later stage and needs a lite-model change first (see §10).
- Cross-module unified tracing (OpenTelemetry etc.): in v1 the timeline comes from lite-agent's own event log.
- A general agent platform, visual orchestration, a plugin marketplace.

### Anti-goals (cases that count as failure even if built)

- The agent can **write** KB entries that take effect directly. The agent can only propose (generate a candidate),
  consistent with steward rule 5 (MCP can only propose).
- Answers that invent sources: a citation must correspond to a passage that was actually retrieved.
- The execution page leaking secrets, API keys, internal URLs or the raw system prompt.
- Depending on the owner's llm-gateway subscription for a demo: a customer deployment must use a model endpoint the
  customer can use.

## 2. Approach (① chosen)

| Approach | How | Trade-off |
| --- | --- | --- |
| **① Its own FastAPI backend, using lite-agent as a library (chosen)** | The backend defines the agent and tools, runs with `lite_agent.Agent` + `PgSessionStore`, and provides the HTTP / SSE, authentication and page-specific endpoints itself; KB and memory are reached through llm-steward's Python SDK (HTTP) | Customer-specific customisation (authentication, branding, tools, page data shapes) all lives in glassdesk; steward and lite-agent stay general |
| ② Use `liteagent serve` directly, glassdesk backend only forwards | Least code | lite-agent's HTTP shell binds loopback only and has no authentication (lite-agent design §10); endpoints and data shapes are fixed by the general shell, and customer customisation would mean changing the library |
| ③ Put it into llm-steward as a new page | Least to deploy | Violates steward's non-goals ("no chat app or agent framework"); customer customisation would pollute the general service |

The owner chose ① on 2026-11-25.

## 3. Overall architecture

```
Browser (frontend: React SPA)
   │ REST + SSE (same origin, via the backend)
   ▼
glassdesk backend (FastAPI, :8740)
   ├─ authentication, sessions, branding config
   ├─ agent run: lite_agent.Agent (roles go through lite-model) + PgSessionStore (database glassdesk)
   │     tools: search_knowledge / propose_knowledge / … (§5)
   ├─ timeline: read the lite-agent event log → project into the steps the page uses (§6)
   └─ llm-steward SDK (HTTP, namespace = this customer)
            │
            ▼
   llm-steward (:8600) ── KB provider (lite-rag / WeKnora / native), memory provider (lite-mem)
            │
   lite-model ──HTTP──► the customer's model endpoint (Ollama / OpenAI-compatible / LiteLLM Proxy)
```

Rules:

1. **glassdesk does not import llm-steward** (workspace rule); it only uses the HTTP mode of `llm-steward-client`
   (not `embedded`).
2. **Every LLM call goes through a lite-model role** (workspace convention); role names are in the configuration, no
   model id is hard-coded.
3. **KB writes only go through steward**: glassdesk stores no knowledge itself; it only stores the agent's session
   events (lite-agent) and the app's own data (users, session list, branding config).
4. **Tests call no real LLM and no real steward**: they use lite-model's `AsyncFakeModel` and a fake steward (§9).

## 4. Pages

```
┌──────────────────────────────────────────────────────────────────────┐
│ [客户 logo] glassdesk    聊天 | 知识库 | 洞察            用户 ▾      │
├──────────────┬───────────────────────────────────┬───────────────────┤
│ 会话列表     │ 用户：报销上限是多少？            │ 执行过程           │
│ · 报销政策   │                                   │ ● 理解问题  0.4s   │
│ · 入职流程   │ 助手：差旅住宿上限每晚 800 元[1]，│ ● search_knowledge │
│              │ 超出需部门审批[2]。               │   "报销 上限"       │
│ + 新会话     │   [1] 差旅制度 v3 §2.1            │   → 5 条，top 0.82 │
│              │   [2] 条目「超标审批」(verified)  │ ● 生成回答  2.1s   │
│              │                                   │ ─────────────────  │
│              │ ┌ 要不要存进知识库？ ──────────┐  │ tokens 1.8k · $0.002│
│              │ │「海外差旅上限每晚 150 美元」 │  │ 总耗时 3.0s        │
│              │ │ [存为团队知识] [只给我] [不要]│  │                   │
│              │ └──────────────────────────────┘  │                   │
│              │ [输入框…]                  [发送] │                   │
└──────────────┴───────────────────────────────────┴───────────────────┘
```

The mockup's text is the Chinese UI and sample data, kept as is. Glosses: 客户 logo (customer logo); 聊天 | 知识库 | 洞察
(Chat | Knowledge base | Insights); 用户 (user); 会话列表 (session list); 报销政策 / 入职流程 (reimbursement policy /
onboarding process); 新会话 (new session); 执行过程 (execution process); 理解问题 (understand the question); 生成回答
(generate the answer); 总耗时 (total time); 要不要存进知识库？ (save to the knowledge base?); 存为团队知识 / 只给我 / 不要
(save as team knowledge / only for me / no); 输入框… (input box…); 发送 (send). The sample question is "报销上限是多少？"
(What is the reimbursement limit?), the sample answer "travel lodging limit is 800 yuan per night [1], above which
department approval is needed [2]".

| Page | Content |
| --- | --- |
| Chat (聊天) | Session list; message stream; citations in an answer can be opened to see the source passage; confirmation cards (steward's `suggestions[]`); the execution panel on the right updates in real time |
| Execution (执行过程) | The full timeline of one answer (opened from the chat; it has a fixed URL that **only logged-in users of this deployment can see**; v1 has no public share link — owner decision, 2026-11-25): per step, its type, input summary, output summary, duration, tokens, cost (when the endpoint does not report cost, show "未知" (unknown), never 0); failed steps are marked red |
| Knowledge base (知识库) | Upload documents; create entries by hand; entry list (status active / verified / deprecated, source, hit count); candidates awaiting confirmation and review; a reviewer can approve / reject; a reviewer or admin can deprecate (停用) an entry still in use, confirmed in the app's own dialog with an optional reason |
| Insights (洞察) | "KB 缺什么" ("what the KB lacks": frequent questions with low retrieval scores), positive / negative ratings of answers, daily usage and cost |

## 5. Agent and tools

One agent (`desk`), with a role such as `desk.answer` (the concrete model is in the lite-model configuration). Tools:

| Tool | Backed by | Notes |
| --- | --- | --- |
| `search_knowledge(query)` | steward `retrieve` (joint memory + KB retrieval, with the current user's scope) | Returns passages, sources, scores; the citations of an answer can only come from these results |
| `propose_knowledge(title, content, reason)` | steward `suggest` | Generates a candidate that follows steward's risk policy (automatic / ask the user / review); the agent cannot write an entry that takes effect directly. At most one per answer: a second call in the same run is refused as a tool error without calling steward. Its result says plainly that the proposal is not in the KB yet and not verified (or, when it went live, that it is not reviewed); the prompt forbids telling the user otherwise |
| `get_entry(entry_id)` | steward `entry_get` | Reads the full text of one entry (used when a citation is expanded) |

What the user said about themselves earlier in the same conversation (history, preferences, situation) may be
used directly, said to come from the conversation and never given a citation number; company knowledge still comes
only from search results (owner, 2026-11-27: answers ignored a fact stated two messages earlier).

When each conversation turn ends, the backend hands that turn's messages to steward `episode_add` (`mode=sync`;
steward extracts memory, scores the KB value and generates candidates) and pushes the returned `suggestions[]` to the
frontend to show cards. The user's decision on a card calls `candidate_accept` / `candidate_reject`. (`mode=sync`
costs one more LLM call of waiting after the answer; the card appears asynchronously after the answer and does not
block the answer from showing — implementer's decision.)

Manual entry: the 知识库 (Knowledge base) page calls `entry_create` / `document_upload`.

**Collection** (implementer's decision, the owner can change it): one customer has one collection `company` by
default, created by `glassdesk setup` (and by `seed --demo`); risk routing uses steward's default policy (low =
automatic, medium = ask the user, high = review), plus one high-risk keyword rule for demos, so that all three write
paths can be triggered under the same configuration (G2's e2e depends on this). Multiple collections (per department)
will be added later as customers need them.

### Admin data and audit (implementer's decision)

- **Insights data**: steward's KB gaps, hit statistics and usage are only on `/admin/v1` (`/admin/v1/ns/{slug}/stats`,
  `retrieval-logs?gaps=true`). The backend holds `STEWARD_ADMIN_TOKEN` on behalf of users (only in the server's
  `.env`, never sent to the browser) and reads these two endpoints with a very thin HTTP client — owner decision,
  2026-11-25, steward is not changed.
- **Two steward keys** (changed after the first real deployment on 2026-11-26): steward treats content **written by
  a key that has the `review` permission itself** as already reviewed and makes it take effect directly. So everything
  a human does (manual entry, AI proposals, confirmation cards, uploads, rating, retrieval) goes through a read/write
  key (`GLASSDESK_STEWARD_API_KEY`) and follows risk routing; only the review queue and review decisions go through the
  key with `review` (`GLASSDESK_STEWARD_REVIEW_KEY`). Originally one key combined three permissions, so a member's
  high-risk entry could bypass review.
- **Reviewer identity**: there is only one review key, so in steward's change_log all reviews are recorded as the same
  actor. glassdesk keeps its own audit table (who, when, on which candidate / entry, what was done) and writes the
  glassdesk user name into the `reason` / `note` field of the steward decision. Deprecating an entry
  (`POST /api/kb/entries/{id}/deprecate`, reviewer / admin) also goes through the review key, after checking
  the entry is in the deployment's collection; steward's deprecate takes no note, so the optional reason is
  kept only in the audit row (`entry_id`, action `deprecate`). Having steward accept a proxied
  reviewer identity is a later cross-repo change, not in v1.
- **Answer feedback**: the UI gives a positive / negative rating to a whole answer. glassdesk stores answer-level
  feedback (the insights page's positive rate uses it); it also records the same rating against every item the answer
  **cited** (steward `feedback(retrieval_id, item_id, helpful)`), so that steward's feedback-driven re-review works.
  Retrieval results that were not cited are not recorded.

## 6. Execution process (timeline)

- Data source: lite-agent's event log (`PgSessionStore`, database `glassdesk`). The events of each run already
  contain run start / end, model calls (with usage), and tool calls and results.
- The backend **projects** the events into the steps the page uses (`step: {kind, title, input_summary,
  output_summary, started_at, duration_ms, usage, cost, status}`), exposing only summaries, never the system prompt,
  secrets or internal URLs (anti-goals).
- Real time: `GET /api/sessions/{id}/stream` pushes new steps over SSE (modelled on the `events/stream` of the
  lite-agent HTTP shell).
- Citations: the citation numbers in an answer map to passages in the `search_knowledge` results; a citation that does
  not match shows no link and is marked on the timeline.
- A search step says where its results came from: "8 条：知识库 5 条，记忆 3 条" / "8 results: 5 from the knowledge
  base, 3 from memory" (entries and documents count as the knowledge base). The counts come from the passages
  glassdesk stored for that call (`run_passages`, keyed by run and call id), not from the tool's text. When steward
  reports a source as down (`RetrieveOut.degraded`: `memory`, `kb`, `rerank`), the tool result and the step name it
  ("（记忆暂时不可用）" / "(memory unavailable)"); a source steward names that glassdesk does not know keeps the general
  "partial" wording.
- Answers are rendered as Markdown (`react-markdown`, raw HTML never rendered, images dropped, links shown as text
  with their URL in parentheses, so nothing in model text can be clicked or loaded to carry data out); a single
  newline stays a line break (`whitespace-pre-line`); `[n]` markers become citation chips wherever they sit (bold,
  list items, link text), never inside code.

## 7. Authentication and users (v1)

- Local accounts inside the deployment: an administrator creates users in the CLI (`glassdesk user create`), with
  roles `member` / `reviewer` / `admin`.
- A `reviewer` can approve / reject candidates on the 知识库 (Knowledge base) page (this corresponds to steward's API
  key with the `review` permission, held by the backend on their behalf).
- The glassdesk user id is used as steward's `user_id` scope, so each user has their own memory.
- Customer SSO (OIDC) is left until a customer asks for it.

## 8. Tech stack and deployment

- backend: Python 3.12, uv, FastAPI, Pydantic v2, SQLAlchemy async + Alembic (the app's own tables), `lite-agent[pg]`
  (release wheel, currently 0.2.4, consistent with the workspace's lite-model 0.8.0), `llm-steward-client` (0.1.0 has
  no release, so it is pinned to a commit with `git+…/llm-steward@<commit>#subdirectory=sdk/python`).
- frontend: pnpm, React + Vite + TypeScript, TanStack Router / Query, shadcn/ui + Tailwind, Playwright; the client is
  generated from the backend's OpenAPI; the confirmation card reuses or follows `SuggestionCard` of
  `@llm-steward/widget`.
- Database: a new database `glassdesk` on the shared PG (app tables + lite-agent's session schema).
- Ports: backend `127.0.0.1:8740`, frontend dev `8741`, e2e `8742` (written into the port table of the workspace
  AGENTS.md).
- Deployment (owner decision 2026-11-25: all-in-one Ollama): one docker compose per customer, containing glassdesk (the
  backend also hosts the frontend static files), llm-steward (KB provider **lite-rag**, memory provider **lite-mem**),
  PG + pgvector, and **Ollama** (chat model + embedding model bge-m3). It does not depend on the customer's cloud
  account and can be demonstrated offline; the cost is that a machine with enough performance is needed, so the
  deployment guide must state the minimum configuration (memory / GPU / disk). The concrete chat model is decided by
  the implementer through the model-selection process (the `llm-model-eval` skill) and written into the lite-model
  configuration. Switching to the customer's OpenAI-compatible endpoint is only a lite-model configuration change; v1
  does not verify it. Branding configuration lives in one yaml (customer name, logo, main colour, welcome text, sample
  questions).
- **One backend process per deployment**: "whether this session has a run in progress" is kept in process memory
  (`runs.py`), and only one run is allowed in a session at a time; multiple workers or replicas first need this state
  moved into the database or the event log (a run without `run_finished` is still running).
- Demo data: `glassdesk seed --demo` writes the documents and entries of a fictional company (clearly marked as demo
  data), which can be cleared after the demo.
- **UI language** (2026-11-27): one setting per deployment, `GLASSDESK_LOCALE` = `zh` (default) or `en`. It sets every
  page (the SPA reads it from `/api/branding` and renders nothing until it is known, so an en deployment never
  flashes Chinese), the agent's system prompt and tool descriptions, the timeline's step titles, HTTP error details,
  a new conversation's title and the demo seed. The timeline recognises tool results written in either locale,
  because event logs outlive a switch. The agent still answers in the language of the question. Stored content
  (KB entries, past answers, conversation titles) is not translated. No per-user language and no switcher in v1.

## 9. Tests

- Unit / integration: `AsyncFakeModel` drives the agent; steward uses an HTTP-level fake (`respx` or an in-process fake
  service), and the tests assert the tool-call requests and the projected timeline steps.
- e2e: Playwright runs against the production build, with the backend on a fake model + fake steward; key flow: ask a
  question → the timeline appears → the answer carries citations → confirmation card → a candidate appears in the
  knowledge base.
- Optional real runs (`-m live`): local Ollama + local steward, only run when the owner asks.

## 10. Stages

| Stage | Content | Acceptance |
| --- | --- | --- |
| G0 Skeleton | Repository, backend / frontend skeletons, check commands (ruff, mypy, pytest, typecheck, lint, build), CI | All checks pass on the empty project |
| G1 Vertical slice: one question, one answer | Login → chat → the agent calls `search_knowledge` → an answer with citations; the timeline shows live over SSE | e2e: after a question the timeline shows a search step, and the answer's citations can be opened |
| G2 Knowledge enters the KB | Episode reporting, confirmation cards, `propose_knowledge`, the 知识库 (Knowledge base) page (upload, manual entries, candidates, review) | e2e: one case per each of the three write paths |
| G3 Insights and feedback | Answer feedback (steward `feedback`), KB gaps, usage and cost | The page data matches what steward returns |
| G4 Delivery | compose, branding config, demo data, deployment guide, verified by deploying from scratch | Deployment on a clean machine following the guide succeeds |
| Later | Cross-repo improvements (noted in the G1 review): lite-agent exports run registration and event-stream polling for glassdesk to reuse; `ToolResultEvent` carries structured data, so citations no longer need a separate `run_passages` table and are no longer counted from text; lite-agent gets a per-run turn limit (today the budget accumulates over the whole session, and glassdesk sets it to 200 turns) | Planned separately |
| Later | Token streaming (lite-model first), cross-module tracing, SSO | Planned separately |

## 11. Left to the implementer

- Directory structure, module split, concrete table schemas.
- The citation format (how the numbers in an answer correspond to the `search_knowledge` results).
- Grouping and wording of timeline steps, projection details.
- The form of the fake steward (respx or an in-process service).
- Frontend component-library details, whether `SuggestionCard` is reused or rewritten by following it (depends on
  whether the widget can be installed outside the steward repository).

## 12. Stage records

### G0 + G1 (2026-11-25, branch `feat/g0-g1`)

- Done: repository and check commands; local-account login (signed cookie carrying `session_version`, so the old
  cookie is invalid after logout); the `desk` agent and `search_knowledge`; the event log projected into steps and
  answers with citations; sessions, asking questions (one run at a time per session, 409), the SSE step stream (cursor
  resume, ending with `answer` + `end`); the chat page (session list, Q&A, citation dialog, execution panel);
  `glassdesk serve --fake` demo mode; e2e (login → ask → timeline → citation).
- Deviations from the plan (details in the plan's execution record): the lite-model configuration is in
  `GLASSDESK_LLM__*` (same as llm-steward), not a separate file; the budget is 200 turns (lite-agent's budget
  accumulates per session); the e2e has the backend host the built frontend directly (8743), and 8742 is not used for
  now; e2e is not in CI yet (it needs PG).
- Problems fixed during close-out: cited passages were grouped by `call_id` across runs, so when the endpoint reused
  the same call id every turn, citations got mixed up (now grouped by run); SSE read the whole log every 250 ms (now it
  reads only new events); citation numbers now run **continuously through the whole session** (before, every search
  started from [1], so after two searches [1] could point to the wrong source); a session whose first run was
  interrupted before anything was written is no longer permanently broken; when a run cannot finish, the stream sends
  `failed`; when search results are incomplete, the timeline marks "部分结果" (partial results); a failed answer shows a
  notice instead of a blank; when the browser abandons the stream (e.g. a 401), the send button is restored.
- Deferred (to be handled around G2):
  - When a run is interrupted in the middle of a tool call (`tool_started` with no result), the next question reports
    `UnresolvedCalls`; lite-agent's `resume` is needed to mark those calls as result-unknown; for now that question
    shows as `failed`.
  - The send button has no double-click protection before the POST returns, so a double click shows a misleading
    "上一个问题还在处理中" (the previous question is still being processed) once.
  - The `Secure` flag of the login cookie depends on the request protocol; behind a TLS-terminating reverse proxy,
    uvicorn needs `--proxy-headers` (state it in the G4 deployment guide, or make it a setting).
  - The session budget is 200 model calls for the whole session (about 100 questions), and after that answers show as
    failed; lite-agent needs to provide a per-run limit.
  - When `keep()` fails to write to the database, it marks a successful search as failed.

### G2 (2026-11-25, branch `feat/g2`)

- Done: all three write paths go through steward — reporting an episode after the answer (steward extracts and scores;
  medium risk produces a confirmation card), the agent's `propose_knowledge`, and manual entry and document upload on
  the 知识库 (Knowledge base) page; the card is confirmed in the chat (存为团队知识 / 只给我 / 不要: save as team
  knowledge / only for me / no); the 知识库 page (entries, documents, "待审核" (pending review)), where reviewers
  approve or reject and write `review_audit`; in demo mode "记住…" ("remember…") triggers a proposal; e2e covers
  proposal → confirmation → taking effect, and high-risk entry → review → "已验证" (verified).
- Authorization: steward trusts any `user_id` sent by a server that holds a key, so "is this card yours" is checked by
  glassdesk before the decision (only that user's cards awaiting confirmation are accepted); review only recognises
  steward's review queue (the review key can decide any candidate).
- The answer does not wait for steward's extraction: as soon as the run ends the session is released and the answer is
  sent; reporting the episode happens outside the session lock, and the stream follows it to the end before sending the
  card and `end`.
- Deviations from the plan: steward's suggestion endpoint has no `reason` field, so the reason of `propose_knowledge`
  is only shown to the model; steward has no endpoint to fetch a candidate by id, so the ownership check uses the first
  page of the list (when a user has more than one page of cards awaiting confirmation, an old card returns 404).
- Deferred: the high-risk keyword rule on a real steward is namespace configuration (`steward ns apply`) that an API
  key cannot change, so the G4 deployment guide states it; the keyword rule in demo mode exists only in the fake
  steward.

### G3 (2026-11-25, branch `feat/g3`)

- Done: 有帮助 / 没帮助 (helpful / not helpful) under an answer (one per person per answer, the latest counts; repeating
  the same rating is not sent to steward again); the rating is forwarded to steward's feedback for every item the
  answer cited; every run records one usage row (a run that raised an exception is also recorded, as failed); the
  insights page (reviewers / admins): answers, failures, tokens, cost over the last 7 days in the deployment time zone
  (unknown cost is not counted as 0 but counted separately; if all are unknown it shows "未知" (unknown)), positive rate
  (unrated answers are not in the denominator; with no ratings it shows "—"), steward's KB statistics and "知识库缺什么"
  ("what the KB lacks") (Admin API; shows "未配置" (not configured) when not configured or unreachable); demo mode is
  marked "演示数据" (demo data).
- Only each user's **first** rating of each answer is forwarded to steward: steward adds one count every time it
  receives one and cannot replace an existing rating, so changing one's mind or toggling back and forth would count the
  same person several times (the security review before the push found this could be used to inflate "pending
  re-review"). A change of mind is recorded only in glassdesk; steward keeps the first rating. To be exact, steward
  needs to store one per (retrieval, item, user) (cross-repo, later).
- Fixed during close-out: asking a question right after the previous answer appeared, while the run had not yet
  released the session, got a 409 (a question now waits up to 3 seconds).

### G4 (2026-11-25, branch `feat/g4`)

- Done: branding configuration (`GLASSDESK_BRAND_NAME / _COLOR / _WELCOME / _EXAMPLES`, public endpoint
  `/api/branding`, with the welcome text and sample questions in the shell, the login page and the empty chat page;
  the colour accepts only `#RRGGBB`); `glassdesk seed --demo` ("示例科技" (Example Tech), 6 knowledge items, titles
  carrying "[演示]" (demo), safe to run repeatedly); `serve --proxy-headers`; the image (the frontend is built once and
  hosted by the backend; migration files are put inside the package, so an installed package carries them too);
  `deploy/`: compose (three PostgreSQL databases, steward and lite-rag built from GitHub at pinned commits, Ollama in
  the `ollama` profile, with the host's Ollama also usable), `init-db.sh`, `steward-ns.yaml` (high-risk keywords),
  `bootstrap.sh` (one-time initialisation: secrets, lite-rag key, steward namespace and keys, admin account), and the
  deployment guide (in Chinese).
- Deviations from the design: the steward image does not contain lite-rag, so lite-rag is a separate service (steward
  reaches it over HTTP); steward must have `STEWARD_KB_LLM` turned on, otherwise it produces no confirmation cards and
  rejects suggestions (422); the demo data has no "clear" command (this port has no endpoint to deactivate entries),
  and the guide describes how to do it.
- Verification: the glassdesk image has been built and checked (migration files and frontend static files are in the
  image); the compose configuration resolves. **The whole from-scratch deployment (bootstrap.sh) has not been run
  yet**: it would start the whole set of long-running services and needs the owner's confirmation (see the delivery
  notes).

### First real deployment (2026-11-26, branch `fix/deploy-first-run`)

Ran `bootstrap.sh` from scratch on this machine with the host Ollama (qwen3:8b, bge-m3), then walked through the whole
flow in a browser, and found and fixed:
- The model configuration of lite-rag (S15) and lite-mem (S14) was changed to lite-model's backends form; the old
  variables made both exit at startup.
- The llm-steward image did not have the `agent` extra installed, but at startup it always imports `lite_agent`: fixed
  in llm-steward, and this repository's pinned steward commit follows.
- Writing entries goes through a 60 s client (steward judges risk first and does embedding); a 10 s client made the
  demo-data writes fail when the model was cold-starting; the earlier test "give model calls a longer timeout"
  verified nothing (respx does not execute timeouts), and was changed to check the timeout carried by the request.
- **Review was bypassed**: one key with `review` made a member's high-risk entry directly "已验证" (verified). Changed
  to two keys (§5).
- The cards steward drafted were in English: with thinking on, qwen3 thinks in English and loses the original language
  when drafting (1 in 9 times it kept Chinese). Steward's drafting prompt gained "do not translate" (9/9 kept Chinese),
  and in the deployment steward and lite-mem turn qwen3's thinking off.
- Frontend: the citation dialog closes on Esc / click outside; while saving an entry the button shows "保存中…"
  (Saving…) and is disabled (steward takes tens of seconds to judge risk, and it used to be submitted twice); the tab
  title uses the customer name; Enter sends, Shift+Enter breaks the line (an Enter that confirms IME input does not
  count); the buttons for sending a question and uploading a document are also disabled while the request is running.
- Close-out: simplify (the candidate's key is chosen only in `HttpSteward._candidates_for`; the review key is otherwise
  used only to create the collection — steward requires the review permission to create a collection, found during the
  from-scratch deployment); Codex had no findings. Not done: a shared connection pool (little review traffic, small
  saving), switching the whole site to `useMutation` (beyond this change's scope). The root cause is in steward ("a key
  with review is treated as reviewed for its own writes"): later an explicit "skip review" switch can be added in
  steward, and glassdesk can then go back to one key.

### UI language (2026-11-27, branch `feat/locale`)

The owner asked for an English UI and chose a per-deployment setting over replacing the Chinese copy.
`GLASSDESK_LOCALE` (`zh` | `en`, §8); zh keeps the copy glassdesk shipped with, byte for byte, so every existing test
and deployment is unchanged. Backend copy lives in `i18n.py` (`Texts`, one instance per locale; the tools' argument
models are subclassed per locale so the model sees field descriptions in the prompt's language), and frontend copy
in `lib/i18n.ts` (`en` is typed against `zh`, so a missing key fails `tsc`; components read it through
`MessagesContext`, which the root route provides). `lib/labels.ts` folded into the dictionaries. The CLI's password
prompt became English like the rest of the CLI (operator text, not UI).
- steward's review gate is a keyword list (`deploy/steward-ns.yaml`): it was Chinese only, so an en deployment's
  pricing / policy / legal content went live unreviewed (the en demo's "Product pricing (needs review)" did). The list
  now holds English words too, matched case-insensitively as steward does; `FakeSteward` mirrors it.
- `<html lang>` follows the locale (`zh-CN` as `index.html` ships it, `en`); Playwright pins `GLASSDESK_LOCALE=zh`
  and the pytest `settings` fixture pins `locale="zh"`, so a developer's `.env` cannot change what the suites see.
- Close-out: simplify (one argument-model factory for every locale, limits declared once; branding prefetched beside
  the session check; dead aliases removed). Codex quota was out (until 2026-12-18), so a Claude subagent reviewed
  instead. Not done: `texts` stays an optional `ZH` default (making it required means rewriting existing tests' calls;
  every production caller passes it); timeline steps still carry backend-written text rather than structured facts
  (an API change beyond this one); the `--fake` demo model and fixed passages stay Chinese (e2e scaffolding, run in zh).

### Browser test fixes (2026-11-27, branch `fix/browser-test-findings`)

A browser walk-through of the running app found six problems; each fix has a test that was seen failing first.
- **Markdown shown raw** (`**800 CNY per night**` literally): `AnswerText` renders with `react-markdown` (no
  `rehype-raw`); a small rehype pass turns matched `[n]` in text nodes into citation chips (also inside bold and list
  items, skipping code); unmatched markers stay text. The chip component is module-level so an open popover survives a
  re-render.
- **Memory invisible on the timeline**: the search step counts knowledge-base and memory results from the stored
  passages (§6).
- **"(partial)" unexplained**: the tool result's first line and the step name what was missing (§6). Old logs with
  the general wording still read as "partial".
- **Duplicate proposals** (two near-identical cards from one answer): a second `propose_knowledge` in one run raises
  `AlreadyProposed`, which lite-agent records as the tool's error result; steward is not called. A first call counts
  unless steward certainly did nothing (connection refused or never made, or a 4xx: `StewardUnavailable.unsent`);
  after a 5xx, a timeout or a cancellation steward may have made the candidate, so a retry is refused too. The timeline shows the refusal as "已提议过，未重复提交" / "already proposed",
  not as a failure.
- **"Proposed with the verified content"**: the proposal results now say the proposal is not in the KB and not
  verified, or for one that went live that it is not reviewed or verified; one prompt line forbids calling a
  proposal verified or saved unless the tool result says so. The previous wordings stay recognised for old logs; the
  `--fake` demo model keeps telling the user the short outcome.
- **No way to deprecate an entry**: route, `StewardPort.deprecate`, Knowledge page button and dialog (§4, §5);
  `review_audit` gains `entry_id` (migration 0007). There was no dialog component yet: `components/ConfirmDialog.tsx`
  is the app's own.

Deliberately not done:
- (a) A cited answer can still misstate its source (seen: three years' service answered as 10 days of leave, while
  the entry says 5 days after one year and 10 after five). Deferred to a measured eval round, not a prompt tweak.
- (b) steward-side issues (a conflict should go to review, draft language, duplicate suggestions) are fixed in
  llm-steward 4816b66 (its PR #27, stacked on #26), and both pins (`backend/pyproject.toml`, `deploy/compose.yaml`)
  follow in this branch. New knowledge near an effective entry, and a member's edit of effective knowledge, now wait
  for a reviewer. The compose `STEWARD_LLM` gains `"roles": {"kb.similar": {"model": "bge-m3:567m"}}`: steward refuses
  to start with `STEWARD_KB_LLM` on and no embedding model for `kb.similar`.
- (c) Every search returning all 5 demo entries raises every entry's hit count. This is by design: steward counts the
  items it returned, while glassdesk records feedback only for the cited ones.
- (e) If the `review_audit` insert fails after steward has deprecated an entry, the entry is out of use with no audit
  row: the same order as approve / reject (steward first, then the audit), accepted.
- (d) The timeline still recognises tool wording: the legacy proposal wording, and every combination of missing
  sources. The general fix is to store per-call facts (degraded sources, proposal stage or refusal) in a table next to
  `run_passages`, read them in the timeline, and keep today's parsing frozen as the fallback for old logs. It is
  deferred because it needs a migration and a decision on backfilling old logs.
