# glassdesk G0 + G1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A runnable glassdesk repo (backend + frontend, every check green) whose first vertical slice works end to end: log in → ask a question → the agent searches the steward KB → the timeline streams in over SSE → the answer shows clickable citations.

**Architecture:** A FastAPI backend runs a `lite_agent.Agent` per message (role via lite-model, events in `PgSessionStore`), with tools that call llm-steward over its Python SDK (HTTP). It projects the agent's event log into page-ready `Step`s and an `Answer` with citations, and streams steps over SSE. A React SPA (served as static files by the backend in production) renders chat, citations and the timeline.

**Tech Stack:** Python 3.12, uv, FastAPI, Pydantic v2, SQLAlchemy 2 async + Alembic, psycopg, `lite-agent[pg]` 0.2.4 wheel, `lite-model` 0.8.0 (via lite-agent's metadata), `llm-steward-client` (git, subdirectory `sdk/python`, pinned commit), pytest + respx. Frontend: Node 22, pnpm 10, React + Vite + TypeScript, TanStack Router/Query, shadcn/ui + Tailwind, `@hey-api/openapi-ts`, Vitest, Playwright.

**Spec:** `glassdesk/docs/glassdesk-design.md` (§3 architecture, §4 pages, §5 tools, §6 timeline, §7 auth, §8 stack, §10 stages G0/G1). G2–G4 get their own plans after G1's close-out.

## Global Constraints

- Repo `lite-ai/glassdesk/`, package `glassdesk`, CLI `glassdesk`, env prefix `GLASSDESK_`.
- Ports: backend `127.0.0.1:8740`, frontend dev `8741`, e2e `8742` (production build + backend in fake mode on `8743`).
- Database `glassdesk` on the shared PG (`localhost:5432`); app tables in schema `glassdesk`, lite-agent events in schema `lite_agent`. Tests use `GLASSDESK_TEST_DATABASE_URL`, schema `glassdesk_test` / `lite_agent_test`, dropped and recreated by fixtures.
- Never import `llm_steward`; only `llm_steward_client.AsyncSteward` over HTTP (no `embedded`).
- Every LLM call goes through a lite-model role; the agent's role is `desk.answer` (configured in `GLASSDESK_MODELS` → a lite-model config file). No model id in code.
- Tests never call a real LLM, real steward, Ollama or llm-gateway: `lite_model.testing.AsyncFakeModel` and `glassdesk.testing.FakeSteward`.
- The timeline never exposes `RunStarted.system`, provenance URLs/`via`, API keys or raw upstream error text (design §1 anti-goals).
- `cost_usd is None` → the API sends `null` and the UI shows "未知", never 0.
- Agent tools may only read or *propose*; no tool writes an effective KB entry (G1 has read-only tools).
- User-facing UI strings are Chinese; code, comments, logs, commits English. Conventional Commits.
- Checks (definition of done for every task): backend `uv run ruff check && uv run ruff format --check && uv run mypy && uv run pytest`; frontend `pnpm typecheck && pnpm lint && pnpm test && pnpm build`.
- Git: no commit without the owner's go-ahead (global rule); each task's "Commit" step means: stage the listed paths, propose the message, wait.

## Review Focus

1. **The model cites `[n]` that no search returned, or cites nothing** → that marker renders as plain text (no link) and the answer's step is flagged `unmatched_citations`; never a link to a wrong passage. Test in Task 7.
2. **steward is down, times out, or returns `degraded`** → `search_knowledge` returns an error tool result (not a 500), the timeline shows that step with `status="error"` (or a "部分结果" note for `degraded`), and the run still finishes. Tests in Tasks 5 and 6.
3. **A second message while a run is going** → `409`, and the UI disables Send until the stream closes. Tests in Tasks 8 and 9.
4. **User B asks for user A's conversation, steps or stream** → `404` (not 403: do not confirm it exists). Test in Task 8.
5. **The SSE stream reconnects mid-run with `Last-Event-ID`/`after`** → no step is sent twice and none is lost. Test in Task 7.

---

### Task 1: Repo and backend skeleton

**Files:**
- Create: `glassdesk/.gitignore`, `glassdesk/README.md`, `glassdesk/AGENTS.md`, `glassdesk/CLAUDE.md` (`@AGENTS.md` + Claude notes), `glassdesk/.env.example`
- Create: `glassdesk/backend/pyproject.toml`, `backend/src/glassdesk/__init__.py`, `config.py`, `app.py`, `cli.py`, `backend/.env.example`
- Create: `glassdesk/.github/workflows/ci.yml` (backend job with a `pgvector/pgvector:pg18` service; frontend job added in Task 2)
- Modify: `lite-ai/AGENTS.md` — add glassdesk to the repo table, the dependency graph (top, beside llm-steward; consumes lite-agent, llm-steward over HTTP) and the ports table.
- Test: `backend/tests/test_health.py`

**Interfaces:**
- Produces: `glassdesk.config.Settings` (pydantic-settings, prefix `GLASSDESK_`, `.env` from cwd): `database_url: str`, `db_schema: str = "glassdesk"`, `agent_schema: str = "lite_agent"`, `steward_url: str = "http://127.0.0.1:8600"`, `steward_api_key: SecretStr`, `models_config: Path` (lite-model config file), `session_secret: SecretStr`, `brand_name: str = "glassdesk"`, `static_dir: Path | None = None`. Rejects any schema ending in `_test` (mirror llm-steward's rule).
- Produces: `glassdesk.app.create_app(settings: Settings, *, deps: Deps | None = None) -> FastAPI`; `Deps` is filled in by later tasks (a dataclass holding the model, store, steward, db engine), built from settings when `None`.
- Produces: CLI `glassdesk serve [--host 127.0.0.1] [--port 8740]`, `glassdesk migrate`.

- [ ] **Step 1:** `git init` in `glassdesk/` (ask the owner first — this creates the repo), default branch `main`; remote `github.com/ArthurGao/glassdesk` only when the owner says so.
- [ ] **Step 2: Write the failing test** `test_health_reports_ok`: `TestClient(create_app(settings)).get("/api/health")` → `200`, `{"status": "ok"}`.
- [ ] **Step 3:** Run `uv run pytest tests/test_health.py -v` → FAIL (module missing).
- [ ] **Step 4:** pyproject: deps above; `[tool.uv.sources]` `lite-agent` = release wheel URL of v0.2.4 (copy the URL form from llm-steward `backend/pyproject.toml`), `llm-steward-client` = `git+https://github.com/ArthurGao/llm-steward@<current main commit>#subdirectory=sdk/python`; dev: pytest, pytest-asyncio, respx, ruff, mypy (strict), httpx. Ruff/mypy settings copied from llm-steward backend. Implement `Settings`, `create_app` with `/api/health`, CLI.
- [ ] **Step 5:** Run all backend checks → green. Run `rg -n 'lite_model-|lite_agent-' glassdesk/backend/pyproject.toml glassdesk/backend/uv.lock` and confirm lite-model resolves to 0.8.0.
- [ ] **Step 6: Commit** `chore: scaffold glassdesk backend` (paths above).

### Task 2: Frontend skeleton and app shell

**Files:**
- Create: `glassdesk/frontend/` (pnpm workspace with a single app at `frontend/` root is fine): `package.json`, `vite.config.ts` (dev port 8741, proxy `/api` → 8740), `tsconfig.json`, `eslint.config.js`, `tailwind` setup, `src/main.tsx`, `src/routes/__root.tsx`, `src/routes/index.tsx` (chat placeholder), `src/routes/knowledge.tsx`, `src/routes/insights.tsx` (both "即将推出"), `src/components/AppShell.tsx`, `playwright.config.ts` (port 8742)
- Modify: `.github/workflows/ci.yml` — frontend job.
- Test: `frontend/src/components/AppShell.test.tsx`

**Interfaces:**
- Produces: `AppShell({brandName, children})` with nav links 聊天 `/`, 知识库 `/knowledge`, 洞察 `/insights`; `pnpm gen:api` script running `@hey-api/openapi-ts` against `http://127.0.0.1:8740/openapi.json` (or a checked-in `openapi.json` exported by `glassdesk openapi > frontend/openapi.json`, preferred so CI needs no server) into `src/client/`.

- [ ] **Step 1: Write the failing test** `renders brand and three nav links in order`: render `<AppShell brandName="Acme">`; expect text `Acme`; links' names in order `["聊天", "知识库", "洞察"]` with hrefs `["/", "/knowledge", "/insights"]`.
- [ ] **Step 2:** `pnpm test` → FAIL.
- [ ] **Step 3:** Implement shell and routes; add `glassdesk openapi` CLI command (prints `create_app(...).openapi()` as JSON) to the backend.
- [ ] **Step 4:** `pnpm typecheck && pnpm lint && pnpm test && pnpm build` → green.
- [ ] **Step 5: Commit** `chore: scaffold glassdesk frontend`.

### Task 3: Database, users and login

**Files:**
- Create: `backend/src/glassdesk/db.py`, `backend/src/glassdesk/users.py`, `backend/src/glassdesk/auth.py`, `backend/alembic.ini`, `backend/migrations/versions/0001_users_conversations.py`
- Modify: `app.py` (routes), `cli.py` (`glassdesk user create <username> --role member|reviewer|admin`, password from prompt or `--password-stdin`)
- Test: `backend/tests/conftest.py` (PG fixtures, schema recreate), `backend/tests/test_auth.py`

**Interfaces:**
- Produces tables (schema `glassdesk`): `users(id uuid pk, username text unique, password_hash text, role text check in ('member','reviewer','admin'), created_at)`, `conversations(id uuid pk, user_id uuid fk, agent_session_id text unique null, title text, created_at, updated_at)` (used from Task 8).
- Produces: `POST /api/auth/login {username, password}` → `200 {username, role}` + `HttpOnly; SameSite=Lax` signed session cookie (itsdangerous, `session_secret`); wrong credentials → `401` with the same body whether user or password is wrong. `POST /api/auth/logout` → `204`. `GET /api/me` → `{username, role}` or `401`.
- Produces dependency `current_user(request) -> User` (`401` when absent/invalid/expired, 7-day expiry). Passwords: argon2 (`argon2-cffi`).

- [ ] **Step 1: Write failing tests:** `test_login_sets_cookie_and_me_returns_user` (role `"member"`), `test_wrong_password_and_unknown_user_give_identical_401`, `test_me_without_cookie_is_401`, `test_tampered_cookie_is_401`, `test_cli_user_create_rejects_duplicate_username` (exit code ≠ 0, one row).
- [ ] **Step 2:** `uv run pytest tests/test_auth.py -v` → FAIL.
- [ ] **Step 3:** Implement models, migration, auth routes, CLI; `glassdesk migrate` runs Alembic and `lite_agent.pg.migrate` for `agent_schema`.
- [ ] **Step 4:** Tests green; all checks green.
- [ ] **Step 5: Commit** `feat(auth): local users and session login`.

### Task 4: Frontend login

**Files:**
- Create: `frontend/src/routes/login.tsx`, `frontend/src/lib/session.ts`
- Modify: `__root.tsx` (redirect to `/login` when `/api/me` is `401`), `AppShell.tsx` (username + 退出)
- Test: `frontend/src/routes/login.test.tsx` (MSW)

- [ ] **Step 1: Write failing tests:** `shows 用户名或密码错误 on 401 and keeps the username`; `navigates to / after 200`.
- [ ] **Step 2:** `pnpm test` → FAIL. **Step 3:** implement with the generated client. **Step 4:** checks green.
- [ ] **Step 5: Commit** `feat(web): login page`.

### Task 5: Steward port and fake

**Files:**
- Create: `backend/src/glassdesk/steward.py`, `backend/src/glassdesk/testing.py`
- Test: `backend/tests/test_steward.py` (respx against the real `AsyncSteward`), `backend/tests/test_fake_steward.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass(frozen=True)
  class Passage:
      item_id: str; kind: Literal["memory", "entry", "document"]
      title: str | None; source: str | None; text: str; score: float; verified: bool

  @dataclass(frozen=True)
  class SearchResult:
      retrieval_id: str; passages: tuple[Passage, ...]; degraded: tuple[str, ...]

  class StewardPort(Protocol):
      async def search(self, query: str, *, user_id: str, session_id: str) -> SearchResult: ...

  class HttpSteward:  # implements StewardPort over llm_steward_client.AsyncSteward
      def __init__(self, base_url: str, api_key: str, *, timeout_s: float = 10.0) -> None: ...
      async def aclose(self) -> None: ...

  class StewardUnavailable(Exception): ...  # connection error, timeout, 5xx; message never carries upstream text
  ```
  `HttpSteward.search` calls `retrieve(query, user_id=, session_id=, format="items")`; `text` = first of `passages` if any else `content`.
- Produces: `glassdesk.testing.FakeSteward(passages: Sequence[Passage] = (), *, fail: bool = False, degraded: tuple[str, ...] = ())` recording `calls: list[tuple[str, str, str]]`.

- [ ] **Step 1: Write failing tests:** `test_search_maps_items_to_passages` (respx returns two items, one with `passages=["p1","p2"]`; assert `text=="p1"`, `kind`, `verified`, `retrieval_id`, and that the request body had `scope.user_id=="u1"`); `test_search_timeout_raises_steward_unavailable`; `test_search_5xx_raises_without_upstream_text` (upstream body `"secret-token-xyz"` not in `str(exc)`); `test_degraded_is_passed_through`.
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** green.
- [ ] **Step 5: Commit** `feat(steward): search port over the steward SDK`.

### Task 6: The desk agent and `search_knowledge`

**Files:**
- Create: `backend/src/glassdesk/agent.py`
- Test: `backend/tests/test_agent.py`

**Interfaces:**
- Consumes: `StewardPort`, `Passage` (Task 5).
- Produces:
  ```python
  ROLE = "desk.answer"
  def build_agent(*, model: AsyncToolModel, sessions: SessionStore, steward: StewardPort,
                  user_id: str, brand_name: str,
                  on_passages: Callable[[str, Sequence[Passage]], Awaitable[None]]) -> lite_agent.Agent
  ```
  One tool, `search_knowledge(args: SearchArgs{query: str (1..500 chars)}, ctx) -> str`, built with `lite_agent.tool(description=...)` as a closure over `steward`, `user_id` and `on_passages`, passing `session_id=ctx.session_id` and calling `on_passages(ctx.call_id, passages)` before returning (Task 8 persists them to `run_passages`). Numbering restarts at 1 in every call; the citation mapper (Task 7) resolves numbers per call. Format per passage: `[{n}] {title or source or kind} — {text}`; zero passages → `没有找到相关内容。`; `degraded` non-empty → prefix line `（部分来源暂时不可用）`; `StewardUnavailable` → raise so lite-agent records an error tool result (check how `ModelTool` turns exceptions into `is_error` results in `lite-agent/src/lite_agent/tools.py`; if it does not, return a tool error explicitly).
  System prompt (Chinese, in `agent.py` as a constant): answer only from `search_knowledge` results; cite with `[n]` exactly as numbered; say you did not find it when nothing relevant came back; never invent sources. `Budget`: at most 6 turns.

- [ ] **Step 1: Write failing tests** (scripted `AsyncFakeModel(**{ROLE: [...]})`; copy the scripting pattern for a tool-call turn followed by a final text turn from `lite-agent/tests/unit/test_loop.py`; `InMemorySessionStore`):
  - `test_search_tool_passes_user_and_session_and_numbers_results` → `FakeSteward.calls == [("报销上限", "u1", result.session_id)]`; the `tool_result` event content starts with `"[1] 差旅制度 v3 — "`.
  - `test_no_results_tool_says_not_found` → content `"没有找到相关内容。"`.
  - `test_steward_down_gives_error_tool_result_and_run_completes` → a `tool_result` with `is_error=True`, content not containing upstream text; `RunResult.outcome == "completed"`.
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** green.
- [ ] **Step 5: Commit** `feat(agent): desk agent with search_knowledge`.

### Task 7: Projection — steps, answer, citations

**Files:**
- Create: `backend/src/glassdesk/timeline.py`
- Test: `backend/tests/test_timeline.py`

**Interfaces:**
- Consumes: lite-agent event models (`lite_agent.events`: `RunStarted`, `UserMessage`, `ModelTurn`, `ToolStarted`, `ToolResultEvent`, `ModelErrorEvent`, `RunFinished`, …).
- Produces:
  ```python
  class Usage(BaseModel): input: int | None; output: int | None; cost_usd: float | None
  class Step(BaseModel):
      seq: int                     # seq of the event that opened the step (SSE id)
      run_id: str
      kind: Literal["question", "thinking", "tool", "answer", "error", "finished"]
      title: str                   # e.g. "搜索知识库", "生成回答"
      detail: str | None           # tool: query + "→ N 条" summary; never system prompt / provenance
      status: Literal["running", "ok", "error"]
      started_at: datetime; duration_ms: int | None; usage: Usage | None
  class Citation(BaseModel):
      n: int; item_id: str; kind: str; title: str | None; source: str | None; text: str; verified: bool
  class Answer(BaseModel):
      run_id: str; text: str; citations: list[Citation]; unmatched: list[int]
  def project_steps(events: Sequence[Event]) -> list[Step]
  def project_answer(events: Sequence[Event], passages_by_call: Mapping[str, Sequence[Passage]], run_id: str) -> Answer | None
  ```
  `tool` steps pair `ToolStarted` with its `ToolResultEvent` (status `error` when `is_error`; `running` when unpaired). `finished` carries the run's summed usage. Citations: `[n]` markers in the run's last assistant text map to the passages of **the most recent `search_knowledge` call in the same run that has an `n`th passage**; others go to `unmatched`. `passages_by_call` is keyed by `call_id` (filled through Task 6's `on_passages`, read back from `run_passages` in Task 8).
- [ ] **Step 1: Write failing tests:**
  - `test_steps_pair_tool_calls_and_hide_system_prompt` (build events by hand; `RunStarted.system="SECRET-PROMPT"`; assert kinds in order `["question","tool","answer","finished"]`, tool `status=="ok"`, and `"SECRET-PROMPT"` absent from `json.dumps([s.model_dump(mode="json") for s in steps])`).
  - `test_unknown_cost_stays_null` (`UsageData(cost_usd=None)` → `finished.usage.cost_usd is None`).
  - `test_answer_maps_markers_and_reports_unmatched` (text `"上限 800 元[1]，需审批[3]。"`, two passages → citations `[1]`, `unmatched == [3]`).
  - `test_answer_without_markers_has_no_citations`.
  - `test_steps_after_seq_are_a_suffix` (`project_steps(events)` filtered to `seq > k` equals projecting with a cursor — the function the SSE route uses must not duplicate or drop: implement `steps_after(events, after_seq) -> list[Step]` and test both a cut between `ToolStarted` and its result (the tool step is re-sent with `status` updated, same `seq`) and a cut after `RunFinished` (empty)).
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** green.
- [ ] **Step 5: Commit** `feat(timeline): project agent events into steps and cited answers`.

### Task 8: Conversations, runs and the SSE stream

**Files:**
- Create: `backend/src/glassdesk/conversations.py` (routes + service), `backend/src/glassdesk/runs.py` (one-run-per-conversation registry, background tasks, drain on shutdown)
- Modify: `app.py`, `Deps` (model from `lite_model.build_async(load(models_config))` — check the exact loader name in `lite_model/config.py`; `PgSessionStore(database_url, schema=agent_schema)`; `HttpSteward`), migration `0002_run_passages.py`
- Test: `backend/tests/test_conversations.py`

**Interfaces:**
- Produces table `run_passages(run_id text, call_id text, n int, passage jsonb, primary key (run_id, call_id, n))`.
- Produces routes (all need `current_user`; a conversation of another user → `404`):
  - `POST /api/conversations` → `201 {id, title: "新会话", created_at}`
  - `GET /api/conversations` → the user's, newest `updated_at` first
  - `POST /api/conversations/{id}/messages {text: 1..4000 chars}` → `202 {run_id}`; a run already going → `409`; first message sets `title` to its first 30 chars.
  - `GET /api/conversations/{id}/steps?after=0` → `list[Step]`
  - `GET /api/conversations/{id}/stream?after=N` → SSE `event: step`, `id: <seq>`, `data: Step`; honours `Last-Event-ID` over `after`; after `finished` sends `event: answer` with `Answer` and closes. Poll interval 0.25 s (same approach as `lite_agent.server.stream_events`).
  - `GET /api/conversations/{id}/answers` → `list[Answer]`, one per finished run, in order.
- [ ] **Step 1: Write failing tests** (app with `Deps(model=AsyncFakeModel(...), sessions=PgSessionStore on test schema, steward=FakeSteward(...))`, httpx `AsyncClient` + ASGI transport):
  - `test_ask_streams_steps_then_answer` → event types `["step"]*k + ["answer"]`; step kinds include `"tool"`; answer `citations[0].n == 1`.
  - `test_second_message_while_running_is_409` (fake model blocks on an `asyncio.Event` until released).
  - `test_other_users_conversation_is_404` for messages, steps, stream and answers.
  - `test_stream_resumes_from_last_event_id_without_duplicates` (read until the first `tool` step, reconnect with `Last-Event-ID`, assert the union of seqs has no duplicates and ends with `answer`).
  - `test_steward_down_run_finishes_with_error_step` (`FakeSteward(fail=True)` → a step `kind=="tool", status=="error"`, then `answer`).
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** green on PG.
- [ ] **Step 5: Commit** `feat(chat): conversations, runs and step stream`.

### Task 9: Chat page with timeline and citations

**Files:**
- Create: `frontend/src/features/chat/{ConversationList,MessageThread,Composer,CitationChip,TimelinePanel}.tsx`, `frontend/src/features/chat/useStepStream.ts` (EventSource, reconnect handled by the browser via `id`)
- Modify: `routes/index.tsx`
- Test: `frontend/src/features/chat/*.test.tsx` (MSW, a mock EventSource)

**Interfaces:**
- Consumes: Task 8 routes via the generated client (`pnpm gen:api` after `glassdesk openapi`).
- Layout per design §4 sketch: conversation list left, thread middle, timeline right. `CitationChip` renders `[n]` as a button opening a popover with title, source, text and a "已验证" badge when `verified`; `unmatched` numbers render as plain text. Timeline row: icon by `status`, `title`, `detail`, duration, tokens; footer total tokens + cost ("未知" when `null`).
- [ ] **Step 1: Write failing tests:** `Send is disabled while a stream is open and re-enabled after answer`; `409 shows 上一个问题还在处理中`; `citation [1] opens popover with passage text; unmatched [3] is not a button`; `timeline shows 未知 when cost_usd is null`; `error step renders with error styling and the run still shows its answer`.
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** checks green.
- [ ] **Step 5: Commit** `feat(web): chat with live timeline and citations`.

### Task 10: Fake mode, e2e, static serving

**Files:**
- Create: `backend/src/glassdesk/fakes.py` (a `Deps` built from `FakeSteward` with three demo passages and a scripted `AsyncFakeModel` that calls `search_knowledge` then answers with `[1]`) selected by `glassdesk serve --fake` (CLI flag only; no env switch in production settings), `frontend/e2e/ask.spec.ts`
- Modify: `app.py` — serve `static_dir` (SPA fallback to `index.html` for non-`/api` paths); `playwright.config.ts` webServer: build frontend, run `glassdesk serve --fake --port 8743` against a throwaway test schema, preview on 8742.
- Test: `frontend/e2e/ask.spec.ts`, `backend/tests/test_static.py`

- [ ] **Step 1: Write failing tests:** `test_spa_fallback_serves_index_for_unknown_paths_but_not_api` (`/knowledge` → index.html; `/api/nope` → 404 JSON); e2e `ask a question: timeline shows 搜索知识库 then the answer, citation opens the passage` (log in with a user created in global setup; assert row titles in order `["问题", "搜索知识库", "生成回答", "完成"]` — whatever Task 7's titles are, assert the exact list).
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** `pnpm e2e` green; all checks green.
- [ ] **Step 5: Commit** `test(e2e): ask flow against fake mode; serve the SPA`.

### Task 11: G1 close-out

- [ ] **Step 1:** `/simplify` on the full G0+G1 diff; apply.
- [ ] **Step 2:** Codex review of the whole diff (`codex exec -s read-only … "Review git diff <root commit>…"` per the llm-steward CLAUDE.md form, or the global companion script); triage, fix valid findings red → green, write rejected ones with reasons into the design's stage record (§10 G1).
- [ ] **Step 3:** Re-run every check (backend four + pytest on PG, frontend four + `pnpm e2e`); paste outputs.
- [ ] **Step 4:** Opt-in, only if the owner asks: one live run (`glassdesk serve` against local steward + Ollama) to see a real answer.
- [ ] **Step 5:** Update design §10 (G0/G1 ticked, deferred items), `AGENTS.md` current stage; propose the commit.
