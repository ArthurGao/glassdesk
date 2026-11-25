# glassdesk G2 Implementation Plan — knowledge into the KB

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (owner chose inline execution for G0+G1; same here). Steps use checkbox (`- [ ]`) syntax.

**Goal:** All three ways knowledge enters the KB work end to end through llm-steward: the AI decides (episode after each answer → steward scores it → low risk goes live, medium becomes a confirmation card, high goes to review), the agent proposes (`propose_knowledge`), and a person types an entry or uploads a document. Reviewers approve or reject on the knowledge page.

**Architecture:** glassdesk never decides governance itself: every write is a steward call (`suggest`, `episodes.add`, `kb.entries.create`, `kb.documents.upload`, `candidates.accept/reject`), and the page shows what steward returns. glassdesk adds only what steward cannot know: which glassdesk user may act on which card, the reviewer role, and an audit row of who reviewed what (design §5 "审核身份").

**Tech Stack:** as G1. **Spec:** `docs/glassdesk-design.md` §4 (知识库 page), §5 (tools, collection, audit), §7 (roles), §10 G2.

## Global Constraints

- One steward API key, held by the backend, with scopes `read`, `write`, `review` (`GLASSDESK_STEWARD_API_KEY`). A card decision always passes `user_id` (steward records the end user); a review decision never does (steward records the key as reviewer).
- steward trusts the key holder with any `user_id`: **glassdesk checks that a card's `requested_for_user` is the logged-in user before deciding it** (404 otherwise).
- Review endpoints: role `reviewer` or `admin` only (403 for `member`).
- Collection: one per deployment, name `GLASSDESK_STEWARD_COLLECTION` (default `company`), created by `glassdesk setup` if missing; its id is resolved once per process and cached.
- Agent tools still never write an effective entry: `propose_knowledge` → steward `suggest` (a candidate).
- Episode reporting after a run uses `mode="sync"` and never blocks or fails the answer: errors are logged, the stream still ends; suggestions arrive as an SSE `suggestions` event after `answer`.
- UI copy Chinese; unknown counts shown as "—", never 0.

## Review Focus

1. A user decides a card that belongs to another user (guessing its id) → 404, steward never called. Test in Task 3.
2. steward down while reporting the episode → the answer still arrives, no suggestions, stream ends with `end`. Test in Task 3.
3. A member calls a review endpoint → 403. Test in Task 5.
4. Upload of an empty file or one over 20 MB → 422 before steward is called. Test in Task 5.
5. A card accepted twice (double click) → second decision returns steward's 409 as 409 "已处理", UI removes the card. Test in Task 3 and Task 6.

---

### Task 1: Knowledge port (collection, entries, documents)

**Files:** Modify `backend/src/glassdesk/steward.py`, `testing.py`, `config.py`, `cli.py` (`glassdesk setup`). Test `tests/test_steward_kb.py`.

**Interfaces (produces):**
```python
@dataclass(frozen=True)
class Entry: id: str; title: str; content: str; status: str; risk_level: str; origin: str; hit_count: int | None; updated_at: datetime
@dataclass(frozen=True)
class Document: id: str; title: str; filename: str; status: str; state: str; size_bytes: int; updated_at: datetime
@dataclass(frozen=True)
class Candidate: id: str; stage: Literal["awaiting_user","awaiting_review"]; status: str; risk_level: str; title: str; content: str; reason: str | None; requested_for_user: str | None; origin: str; created_at: datetime
@dataclass(frozen=True)
class Written: entry: Entry | None; candidate: Candidate | None   # exactly one set
class StewardPort(Protocol):   # adds to G1's search
    async def ensure_collection(self, name: str) -> str
    async def list_entries(self) -> list[Entry]
    async def create_entry(self, title: str, content: str, *, author: str) -> Written
    async def list_documents(self) -> list[Document]
    async def upload_document(self, filename: str, data: bytes, mime: str, *, title: str | None) -> tuple[Document, Candidate | None]
```
`Candidate.title/content` come from `draft["title"]`, `draft["content"]` (fallback `draft.get("text", "")`). `author` goes into the entry's `source_refs` as `{"type": "glassdesk_user", "id": author}`. Errors → `StewardUnavailable` (connection / 5xx) or `StewardRejected(status, message)` for 4xx (message is steward's `detail` only when it is a short string; never the raw body).

- [ ] Tests (respx): each method maps fields and request bodies (collection id in body/form); `ensure_collection` lists then creates once; a 422 becomes `StewardRejected(422, …)`; FakeSteward: `create_entry` → active entry for low risk, candidate `awaiting_review` when title/content contains a high-risk word (价格|政策|法务|医疗|安全).
- [ ] Implement; `glassdesk setup` prints the collection id.
- [ ] Commit `feat(steward): knowledge port`.

### Task 2: Governance port (episodes, suggestions, candidates, decisions)

**Interfaces (produces):**
```python
    async def report_episode(self, messages: Sequence[tuple[str, str]], *, user_id: str, session_id: str) -> list[Candidate]
    async def suggest(self, text: str, *, user_id: str, reason: str | None) -> Written
    async def list_candidates(self, *, stage: str, user_id: str | None = None) -> list[Candidate]
    async def get_candidate(self, candidate_id: str) -> Candidate | None   # via list filter; None when unknown
    async def decide(self, candidate_id: str, accept: bool, *, user_id: str | None, scope: Literal["personal","team"] | None = None, note: str | None = None) -> Decision
@dataclass(frozen=True)
class Decision: candidate: Candidate; entry: Entry | None
```
FakeSteward: `report_episode` returns one `awaiting_user` card when any message contains "记住"; `suggest` → `awaiting_review` for high-risk words else `awaiting_user` for `user_id`; `decide` accept+team on medium → entry active; accept+personal → no entry; twice → `StewardRejected(409, "already decided")`.

- [ ] Tests (respx + fake), implement, commit `feat(steward): governance port`.

### Task 3: Cards in the chat (backend)

- After a run finishes (in `work()`), `report_episode([("user", question), ("assistant", answer)], user_id, session_id)`; store returned cards' ids nowhere — the stream end sends `event: suggestions` with `list[CardOut]` fetched by `list_candidates(stage="awaiting_user", user_id=…)` filtered to `requested_for_user == user`. Errors in reporting are logged and ignored.
- Routes: `GET /api/suggestions` (the user's open cards), `POST /api/suggestions/{id}/accept {scope: "personal"|"team"}`, `POST /api/suggestions/{id}/reject`. Before deciding: `get_candidate`; not the user's or not `awaiting_user` → 404. steward 409 → 409 "已处理".
- `CardOut {id, title, content, risk_level, reason}`.
- [ ] Tests: stream ends `answer, suggestions, end` when the fake returns a card; steward down during reporting → `answer, end` (no suggestions event) and the run's answer intact; another user's card → 404 and the fake saw no decision; accept twice → 409; reject removes it from `GET /api/suggestions`.
- [ ] Commit `feat(chat): confirmation cards`.

### Task 4: `propose_knowledge` tool

- `propose_knowledge(args: {title: 1..120, content: 1..2000, reason: 0..300}) -> str` → `suggest(f"{title}\n{content}", user_id, reason)`. Result text: `已提交，等待你确认。` (awaiting_user) / `已提交，等待审核。` (awaiting_review) / `已存入知识库。` (entry). System prompt gains one line: propose only knowledge the user stated or confirmed, never guesses.
- Timeline title `提议存入知识库`, detail = title + `→ 待确认|待审核|已存入|失败`.
- [ ] Tests: the tool result per outcome; timeline detail; the tool is offered (agent tools tuple has both names).
- [ ] Commit `feat(agent): propose_knowledge`.

### Task 5: Knowledge API (entries, documents, review queue, audit)

- `GET /api/kb/entries`, `POST /api/kb/entries {title 1..200, content 1..20000}` → `WrittenOut {entry?, candidate?}`.
- `GET /api/kb/documents`, `POST /api/kb/documents` multipart `file` (+ optional `title`); empty or > 20 MB → 422; allowed types: pdf, docx, md, txt, html.
- `GET /api/kb/reviews` (reviewer/admin): `list_candidates(stage="awaiting_review")`. `POST /api/kb/reviews/{id}/approve|reject {note?}` → `decide(user_id=None, note=f"{username}: {note}")`, then insert `review_audit(id, candidate_id, user_id, action, note, created_at)` (migration 0005).
- [ ] Tests: member → 403 on all review routes; approve writes one audit row with the user and action; empty/oversized upload → 422 and fake saw no upload; entry creation returns the fake's entry or candidate.
- [ ] Commit `feat(kb): knowledge API and review queue`.

### Task 6: Cards in the chat (frontend)

- After an `answer`, the stream's `suggestions` event fills `chatKeys.suggestions`; cards render under the thread: title, content, buttons `存为团队知识` / `只给我` / `不要`. Accept/reject call the API and drop the card; 409 drops it too.
- [ ] Tests: card appears after the event; `存为团队知识` posts `scope: "team"` and removes the card; 409 removes it and shows nothing alarming.
- [ ] Commit `feat(web): confirmation cards`.

### Task 7: Knowledge page (frontend)

- Tabs `条目` / `文档` / `待审核` (the last only for reviewer/admin; hidden for member). Entry list: title, status badge (生效/已验证/待审核…), risk, hit count ("—" when null). `新建条目` form. Document upload (file input + title) with status. Review list with `批准` / `拒绝` (+ optional note).
- [ ] Tests: member sees no 待审核 tab; new entry that comes back as a candidate shows "已提交审核"; approve removes the row.
- [ ] Commit `feat(web): knowledge page`.

### Task 8: e2e and fake mode

- Fake mode: the demo model calls `propose_knowledge` when the question starts with `记住`; FakeSteward is shared across requests (in-memory governance).
- e2e (logged in as an `admin` e2e user): (1) `记住：报销要在 30 天内提交` → timeline shows `提议存入知识库` → card appears → `存为团队知识` → knowledge page lists it as 生效; (2) manual entry with `价格` → shows 待审核 → approve on 待审核 tab → listed as 已验证/生效.
- [ ] Commit `test(e2e): three write paths`.

### Task 9: Close-out

Simplify (4 agents) → Codex review → fresh reviewer → fixes RED→GREEN → all checks → design §12 record → merge per owner.
