"""Test doubles for the boundaries glassdesk does not own (also used by `serve --fake`)."""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from glassdesk.steward import (
    HIGH_RISK_WORDS,
    Candidate,
    Document,
    Entry,
    Passage,
    SearchResult,
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
