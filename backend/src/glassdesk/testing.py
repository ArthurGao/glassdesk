"""Test doubles for the boundaries glassdesk does not own (also used by `serve --fake`)."""

import uuid
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Literal

from glassdesk.steward import (
    HIGH_RISK_WORDS,
    Candidate,
    Decision,
    Document,
    Entry,
    Passage,
    SearchResult,
    StewardRejected,
    StewardUnavailable,
    Written,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _high_risk(*texts: str) -> bool:
    return any(word in text for text in texts for word in HIGH_RISK_WORDS)


class FakeSteward:
    """A StewardPort with fixed search passages and an in-memory KB that applies steward's
    default policy: low risk goes live, high risk (a keyword) waits for review."""

    def __init__(
        self,
        passages: Sequence[Passage] = (),
        *,
        fail: bool = False,
        degraded: tuple[str, ...] = (),
    ) -> None:
        self.passages = tuple(passages)
        self.fail = fail
        self.degraded = degraded
        self.calls: list[tuple[str, str, str]] = []
        self.entries: list[Entry] = []
        self.documents: list[Document] = []
        self.candidates: list[Candidate] = []

    def _check(self) -> None:
        if self.fail:
            raise StewardUnavailable("ConnectError")

    async def search(self, query: str, *, user_id: str, session_id: str) -> SearchResult:
        self.calls.append((query, user_id, session_id))
        self._check()
        return SearchResult(
            retrieval_id=f"fake-{len(self.calls)}", passages=self.passages, degraded=self.degraded
        )

    async def ensure_collection(self) -> str:
        self._check()
        return "fake-collection"

    async def list_entries(self) -> list[Entry]:
        self._check()
        return list(self.entries)

    def _candidate(
        self, title: str, content: str, *, stage: str, user: str | None, origin: str
    ) -> Candidate:
        candidate = Candidate(
            id=str(uuid.uuid4()),
            stage=stage,  # type: ignore[arg-type]
            status="pending",
            risk_level="high" if stage == "awaiting_review" else "medium",
            title=title,
            content=content,
            reason="命中高风险关键词" if stage == "awaiting_review" else None,
            requested_for_user=user,
            origin=origin,
            created_at=_now(),
        )
        self.candidates.append(candidate)
        return candidate

    def _entry(self, title: str, content: str, *, status: str, origin: str) -> Entry:
        entry = Entry(
            id=str(uuid.uuid4()),
            title=title,
            content=content,
            status=status,
            risk_level="low",
            origin=origin,
            hit_count=None,
            updated_at=_now(),
        )
        self.entries.append(entry)
        return entry

    async def create_entry(self, title: str, content: str, *, author: str) -> Written:
        self._check()
        if _high_risk(title, content):
            cand = self._candidate(title, content, stage="awaiting_review", user=None, origin="api")
            return Written(entry=None, candidate=cand)
        return Written(
            entry=self._entry(title, content, status="active", origin="manual"), candidate=None
        )

    async def list_documents(self) -> list[Document]:
        self._check()
        return list(self.documents)

    async def upload_document(
        self, filename: str, data: bytes, mime: str, *, title: str | None
    ) -> tuple[Document, Candidate | None]:
        self._check()
        doc = Document(
            id=str(uuid.uuid4()),
            title=title or filename,
            filename=filename,
            status="processing",
            state="active",
            size_bytes=len(data),
            updated_at=_now(),
        )
        self.documents.append(doc)
        return doc, None

    async def report_episode(
        self, messages: Sequence[tuple[str, str]], *, user_id: str, session_id: str
    ) -> list[Candidate]:
        """A card for the user when they asked to remember something (steward's extraction
        would score it worth keeping and medium risk)."""
        self._check()
        said = next((text for role, text in messages if role == "user" and "记住" in text), None)
        if said is None:
            return []
        fact = said.split("记住", 1)[1].lstrip("：: ")
        if any(c.content == fact and c.status == "pending" for c in self.candidates):
            return []  # already proposed in this run: steward's extraction would dedupe it
        return [
            self._candidate(
                fact[:30], fact, stage="awaiting_user", user=user_id, origin="extraction"
            )
        ]

    async def suggest(self, text: str, *, user_id: str, session_id: str) -> Written:
        self._check()
        title, _, content = text.partition("\n")
        high = _high_risk(text)
        stage = "awaiting_review" if high else "awaiting_user"
        cand = self._candidate(
            title,
            content or title,
            stage=stage,
            user=None if high else user_id,
            origin="user_suggestion",
        )
        return Written(entry=None, candidate=cand)

    async def list_candidates(self, *, stage: str, user_id: str | None = None) -> list[Candidate]:
        self._check()
        return [
            c
            for c in self.candidates
            if c.stage == stage
            and c.status == "pending"
            and (user_id is None or c.requested_for_user == user_id)
        ]

    async def decide(
        self,
        candidate_id: str,
        accept: bool,
        *,
        user_id: str | None,
        scope: Literal["personal", "team"] | None = None,
        note: str | None = None,
    ) -> Decision:
        self._check()
        i, cand = next((i, c) for i, c in enumerate(self.candidates) if c.id == candidate_id)
        if cand.status != "pending":
            raise StewardRejected(409, "already decided")
        decided = replace(cand, status="accepted" if accept else "rejected")
        self.candidates[i] = decided
        entry = None
        if accept and (scope == "team" or user_id is None):
            status = "verified" if user_id is None else "active"  # a reviewer's approval verifies
            entry = self._entry(cand.title, cand.content, status=status, origin="user_suggestion")
        return Decision(candidate=decided, entry=entry)
