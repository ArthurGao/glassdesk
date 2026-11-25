"""What glassdesk needs from llm-steward, over its HTTP SDK (never `llm_steward` itself)."""

import asyncio
import logging
from collections.abc import Awaitable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, Protocol

import httpx
from llm_steward_client import AsyncSteward, StewardError
from llm_steward_client import _models as m
from llm_steward_client._client import AsyncCandidates

if TYPE_CHECKING:
    from glassdesk.config import Settings

log = logging.getLogger(__name__)

_DETAIL_CHARS = 200


@dataclass(frozen=True)
class Passage:
    item_id: str
    kind: Literal["memory", "entry", "document"]
    title: str | None
    source: str | None  # steward's "memory" or "kb"
    text: str
    score: float
    verified: bool


@dataclass(frozen=True)
class SearchResult:
    retrieval_id: str
    passages: tuple[Passage, ...]
    degraded: tuple[str, ...]  # what steward could not reach; the rest stands


@dataclass(frozen=True)
class Entry:
    id: str
    title: str
    content: str
    status: str
    risk_level: str
    origin: str
    hit_count: int | None
    updated_at: datetime


@dataclass(frozen=True)
class Document:
    id: str
    title: str
    filename: str
    status: str  # pending | processing | ready | failed
    state: str  # governance state: draft | active | …
    size_bytes: int
    updated_at: datetime


@dataclass(frozen=True)
class Candidate:
    id: str
    stage: Literal["awaiting_user", "awaiting_review"]
    status: str
    risk_level: str
    title: str
    content: str
    reason: str | None
    requested_for_user: str | None
    origin: str
    created_at: datetime


@dataclass(frozen=True)
class Written:
    """What a write became: a live entry, or a candidate waiting for someone."""

    entry: Entry | None
    candidate: Candidate | None


@dataclass(frozen=True)
class KbStats:
    entries_by_status: dict[str, int]
    pending_reviews: int
    awaiting_user: int
    gaps: list[tuple[str, int]]  # (question, how often) that found nothing good
    demo: bool = False  # made-up numbers (fake mode)


@dataclass(frozen=True)
class Decision:
    candidate: Candidate
    entry: Entry | None  # the entry an accepted team decision made live


class StewardUnavailable(Exception):
    """steward could not answer. The message never carries steward's own text."""


class StewardRejected(Exception):
    """steward refused the request (4xx). `message` is steward's short detail, for the page."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"{status}: {message}")
        self.status, self.message = status, message


class StewardPort(Protocol):
    async def search(self, query: str, *, user_id: str, session_id: str) -> SearchResult: ...
    async def ensure_collection(self) -> str: ...
    async def list_entries(self) -> list[Entry]: ...
    async def create_entry(self, title: str, content: str, *, author: str) -> Written: ...
    async def list_documents(self) -> list[Document]: ...
    async def upload_document(
        self, filename: str, data: bytes, mime: str, *, title: str | None
    ) -> tuple[Document, Candidate | None]: ...
    async def report_episode(
        self, messages: Sequence[tuple[str, str]], *, user_id: str, session_id: str
    ) -> list[Candidate]: ...
    async def suggest(self, text: str, *, user_id: str, session_id: str) -> Written: ...
    async def feedback(self, retrieval_id: str, item_id: str, *, helpful: bool) -> None: ...
    async def stats(self) -> KbStats | None: ...
    async def list_candidates(
        self, *, stage: str, user_id: str | None = None
    ) -> list[Candidate]: ...
    async def decide(
        self,
        candidate_id: str,
        accept: bool,
        *,
        user_id: str | None,
        scope: Literal["personal", "team"] | None = None,
        note: str | None = None,
    ) -> Decision: ...


def _entry(e: m.EntryOut) -> Entry:
    return Entry(
        id=str(e.id),
        title=e.title,
        content=e.content,
        status=e.status,
        risk_level=e.risk_level,
        origin=e.origin,
        hit_count=e.hit_count,
        updated_at=e.updated_at,
    )


def _candidate(c: m.CandidateOut | m.DecisionOut) -> Candidate:
    draft: dict[str, Any] = c.draft
    return Candidate(
        id=str(c.id),
        stage=c.stage,
        status=c.status,
        risk_level=c.risk_level,
        title=str(draft.get("title") or ""),
        content=str(draft.get("content") or draft.get("text") or ""),
        reason=c.reason,
        requested_for_user=c.requested_for_user,
        origin=c.origin,
        created_at=c.created_at,
    )


def _written(out: m.Written) -> Written:
    return Written(
        entry=_entry(out.entry) if out.entry else None,
        candidate=_candidate(out.candidate) if out.candidate else None,
    )


def _document(d: m.DocumentOut) -> Document:
    return Document(
        id=str(d.id),
        title=d.title,
        filename=d.filename,
        status=d.status,
        state=d.state,
        size_bytes=d.size_bytes,
        updated_at=d.updated_at,
    )


async def _call[T](what: str, call: Awaitable[T]) -> T:
    """One steward call: a refusal (4xx) keeps steward's short detail for the page; anything
    else (unreachable, 5xx, a credential problem) is only "unavailable", without steward's text."""
    try:
        return await call
    except StewardError as exc:
        if exc.status in (404, 409, 422):
            detail = exc.detail if len(exc.detail) <= _DETAIL_CHARS else exc.code
            raise StewardRejected(exc.status, detail) from None
        log.warning("steward %s failed: %s %s", what, exc.status, exc.code)
        raise StewardUnavailable(type(exc).__name__) from None
    except OSError as exc:
        log.warning("steward %s failed: %s", what, type(exc).__name__)
        raise StewardUnavailable(type(exc).__name__) from None


class HttpSteward:
    @classmethod
    def from_settings(cls, settings: "Settings") -> "HttpSteward":
        admin = settings.steward_admin_token
        return cls(
            settings.steward_url,
            settings.steward_api_key.get_secret_value(),
            settings.steward_review_key.get_secret_value(),
            collection=settings.steward_collection,
            admin_token=admin.get_secret_value() if admin else None,
            namespace=settings.steward_namespace,
        )

    def __init__(
        self,
        base_url: str,
        api_key: str,
        review_key: str,
        *,
        collection: str = "company",
        timeout_s: float = 10.0,
        model_timeout_s: float = 60.0,
        admin_token: str | None = None,
        namespace: str | None = None,
    ) -> None:
        # One attempt: the agent's tool call or the page is where a failure becomes visible.
        self._client = AsyncSteward(base_url, api_key, timeout=timeout_s, max_retries=0)
        # Episodes and suggestions run a model on steward's side (extraction, drafting).
        self._model_client = AsyncSteward(base_url, api_key, timeout=model_timeout_s, max_retries=0)
        # Reviewing only: steward lets a review-scope key's own writes skip review, so everything
        # a person writes goes through the write key above (read, write) and is routed by risk.
        self._review_client = AsyncSteward(base_url, review_key, timeout=timeout_s, max_retries=0)
        self._collection_name = collection
        # The Admin API takes a static bearer token (server-side only, never sent to a browser).
        self._admin: httpx.AsyncClient | None = None
        if admin_token and namespace:
            self._admin = httpx.AsyncClient(
                base_url=base_url,
                timeout=timeout_s,
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            self._namespace = namespace
        self._collection_id: str | None = None
        self._resolving = asyncio.Lock()

    def _candidates_for(self, user_id: str | None) -> AsyncCandidates:
        """Candidates as `user_id` (an end user: the write key) or, without one, as a reviewer (the
        review key). Steward treats the review key's own writes as reviewed, so nothing a person
        writes may come through it; besides reviewing, it only creates the collection."""
        return (self._client if user_id is not None else self._review_client).candidates

    async def aclose(self) -> None:
        await self._client.aclose()
        await self._model_client.aclose()
        await self._review_client.aclose()
        if self._admin is not None:
            await self._admin.aclose()

    async def search(self, query: str, *, user_id: str, session_id: str) -> SearchResult:
        out = await _call(
            "retrieve",
            self._client.retrieve(query, user_id=user_id, session_id=session_id, format="items"),
        )
        return SearchResult(
            retrieval_id=str(out.retrieval_id),
            passages=tuple(
                Passage(
                    item_id=str(i.id),
                    kind=i.kind,
                    title=i.title,
                    source=i.source,
                    text=i.passages[0] if i.passages else i.content,
                    score=i.score,
                    verified=i.verified,
                )
                for i in out.items
            ),
            degraded=tuple(out.degraded),
        )

    async def ensure_collection(self) -> str:
        """The deployment's collection id, created on first use; resolved once per process."""
        async with self._resolving:
            if self._collection_id is None:
                page = await _call("collections", self._client.kb.collections.list())
                found = next((c for c in page.items if c.name == self._collection_name), None)
                if found is None:
                    # a collection's review policy is a reviewer's decision (steward)
                    found = await _call(
                        "create collection",
                        self._review_client.kb.collections.create(self._collection_name),
                    )
                self._collection_id = str(found.id)
            return self._collection_id

    async def list_entries(self) -> list[Entry]:
        col = await self.ensure_collection()
        page = await _call("entries", self._client.kb.entries.list(collection_id=col))
        return [_entry(e) for e in page.items]

    async def create_entry(self, title: str, content: str, *, author: str) -> Written:
        col = await self.ensure_collection()
        out = await _call(
            "create entry",
            # steward judges risk and embeds before answering: a model call on its side
            self._model_client.kb.entries.create(
                col, title, content, source_refs=[{"type": "glassdesk_user", "id": author}]
            ),
        )
        return _written(out)

    async def list_documents(self) -> list[Document]:
        col = await self.ensure_collection()
        page = await _call("documents", self._client.kb.documents.list(collection_id=col))
        return [_document(d) for d in page.items]

    async def upload_document(
        self, filename: str, data: bytes, mime: str, *, title: str | None
    ) -> tuple[Document, Candidate | None]:
        col = await self.ensure_collection()
        out = await _call(
            "upload document",
            self._client.kb.documents.upload(col, file=(filename, data, mime), title=title),
        )
        return _document(out.document), _candidate(out.candidate) if out.candidate else None

    async def report_episode(
        self, messages: Sequence[tuple[str, str]], *, user_id: str, session_id: str
    ) -> list[Candidate]:
        """One question and its answer; steward extracts, scores and returns new cards."""
        out = await _call(
            "episode",
            self._model_client.episodes.add(
                [{"role": role, "content": text} for role, text in messages],
                user_id=user_id,
                session_id=session_id,
                mode="sync",
            ),
        )
        return [_candidate(c) for c in out.suggestions or []]

    async def suggest(self, text: str, *, user_id: str, session_id: str) -> Written:
        col = await self.ensure_collection()
        out = await _call(
            "suggest",
            self._model_client.suggest(col, text, user_id=user_id, session_id=session_id),
        )
        return _written(out)

    async def list_candidates(self, *, stage: str, user_id: str | None = None) -> list[Candidate]:
        """Every pending candidate at `stage`, the user's own when `user_id` is given (without
        one: the review queue, read with the review key): the ownership and queue checks rely on
        the list being whole, so all pages are read."""
        candidates = self._candidates_for(user_id)
        found: list[Candidate] = []
        cursor: str | None = None
        while True:
            page = await _call(
                "candidates",
                candidates.list(stage=stage, status="pending", user_id=user_id, cursor=cursor),
            )
            found.extend(_candidate(c) for c in page.items)
            if page.next_cursor is None:
                return found
            cursor = str(page.next_cursor)

    async def decide(
        self,
        candidate_id: str,
        accept: bool,
        *,
        user_id: str | None,
        scope: Literal["personal", "team"] | None = None,
        note: str | None = None,
    ) -> Decision:
        """With `user_id`: that end user answering their card. Without: a reviewer deciding, with
        the review key."""
        resource = self._candidates_for(user_id)
        call = resource.accept if accept else resource.reject
        out = await _call("decide", call(candidate_id, user_id=user_id, scope=scope, note=note))
        return Decision(candidate=_candidate(out), entry=_entry(out.entry) if out.entry else None)

    async def feedback(self, retrieval_id: str, item_id: str, *, helpful: bool) -> None:
        """A person's verdict on one item a retrieval returned (steward flags entries for review
        from these)."""
        await _call("feedback", self._client.feedback(retrieval_id, item_id, helpful=helpful))

    async def stats(self) -> KbStats | None:
        """The namespace's KB numbers from steward's Admin API; None when it is not configured.
        Unreachable or malformed: StewardUnavailable, like every other call."""
        if self._admin is None:
            return None
        try:
            response = await self._admin.get(f"/admin/v1/ns/{self._namespace}/stats")
            response.raise_for_status()
            data = response.json()
            return KbStats(
                entries_by_status=dict(data["kb_entries"]),
                pending_reviews=int(data["pending_reviews"]),
                awaiting_user=int(data["awaiting_user"]),
                gaps=[(g["query"], int(g["count"])) for g in data["gaps"]],
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            log.warning("steward stats failed: %s", type(exc).__name__)
            raise StewardUnavailable(type(exc).__name__) from None
