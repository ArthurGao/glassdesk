"""The knowledge page: entries, documents and the review queue (design §4, §5).

Every write is a steward call; what comes back (a live entry or a waiting candidate) is shown as
it is. glassdesk adds the reviewer role and an audit row, since steward sees one API key."""

import uuid
from collections.abc import Awaitable
from datetime import datetime
from pathlib import PurePath
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, Table, Text, func, insert
from sqlalchemy.dialects.postgresql import UUID

from glassdesk.auth import CurrentUser
from glassdesk.db import Deps
from glassdesk.steward import (
    Candidate,
    Document,
    Entry,
    StewardPort,
    StewardRejected,
    StewardUnavailable,
)
from glassdesk.users import User, current_role_in, metadata

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
UPLOAD_TYPES = {".pdf", ".docx", ".md", ".txt", ".html"}

review_audit = Table(
    "review_audit",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("candidate_id", Text, nullable=False),
    Column("user_id", UUID(as_uuid=True), nullable=False),
    Column("action", Text, nullable=False),
    Column("note", Text),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

router = APIRouter(prefix="/api/kb")


class EntryOut(BaseModel):
    id: str
    title: str
    content: str
    status: str
    risk_level: str
    origin: str
    hit_count: int | None
    updated_at: datetime


class DocumentOut(BaseModel):
    id: str
    title: str
    filename: str
    status: str
    state: str
    size_bytes: int
    updated_at: datetime


class CandidateOut(BaseModel):
    id: str
    stage: str
    risk_level: str
    title: str
    content: str
    reason: str | None
    origin: str
    created_at: datetime


class WrittenOut(BaseModel):
    entry: EntryOut | None
    candidate: CandidateOut | None


class UploadedOut(BaseModel):
    document: DocumentOut
    candidate: CandidateOut | None


class EntryIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=20000)


class ReviewIn(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class DecisionOut(BaseModel):
    status: str
    entry_status: str | None


def _out[T: BaseModel](model: type[T], value: Entry | Document | Candidate) -> T:
    return model.model_validate(value, from_attributes=True)


def _candidate(c: Candidate | None) -> CandidateOut | None:
    return _out(CandidateOut, c) if c else None


def _steward(request: Request) -> StewardPort:
    deps: Deps = request.app.state.deps
    if deps.steward is None:
        raise HTTPException(503, "知识库未配置")
    return deps.steward


async def _call[T](call: Awaitable[T]) -> T:
    try:
        result = await call
    except StewardRejected as exc:
        raise HTTPException(409 if exc.status == 409 else exc.status, exc.message) from None
    except StewardUnavailable:
        raise HTTPException(503, "知识库暂时不可用") from None
    return result


Reviewer = Annotated[User, Depends(current_role_in("reviewer", "admin"))]


@router.get("/entries")
async def list_entries(request: Request, user: CurrentUser) -> list[EntryOut]:
    entries: list[Entry] = await _call(_steward(request).list_entries())
    return [_out(EntryOut, e) for e in entries]


@router.post("/entries", status_code=201)
async def create_entry(body: EntryIn, request: Request, user: CurrentUser) -> WrittenOut:
    written = await _call(
        _steward(request).create_entry(body.title, body.content, author=user.username)
    )
    return WrittenOut(
        entry=_out(EntryOut, written.entry) if written.entry else None,
        candidate=_candidate(written.candidate),
    )


@router.get("/documents")
async def list_documents(request: Request, user: CurrentUser) -> list[DocumentOut]:
    documents: list[Document] = await _call(_steward(request).list_documents())
    return [_out(DocumentOut, d) for d in documents]


@router.post("/documents", status_code=201)
async def upload_document(
    request: Request,
    user: CurrentUser,
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form(max_length=200)] = None,
) -> UploadedOut:
    filename = PurePath(file.filename or "").name
    if PurePath(filename).suffix.lower() not in UPLOAD_TYPES:
        raise HTTPException(422, "只支持 PDF、Word、Markdown、TXT、HTML 文件")
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if not data:
        raise HTTPException(422, "文件是空的")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(422, "文件不能超过 20 MB")
    mime = file.content_type or "application/octet-stream"
    document, candidate = await _call(
        _steward(request).upload_document(filename, data, mime, title=title or None)
    )
    return UploadedOut(document=_out(DocumentOut, document), candidate=_candidate(candidate))


@router.get("/reviews")
async def list_reviews(request: Request, user: Reviewer) -> list[CandidateOut]:
    queue: list[Candidate] = await _call(_steward(request).list_candidates(stage="awaiting_review"))
    return [_out(CandidateOut, c) for c in queue]


async def _review(
    request: Request,
    user: User,
    candidate_id: str,
    action: Literal["approve", "reject"],
    note: str | None,
) -> DecisionOut:
    steward = _steward(request)
    queue: list[Candidate] = await _call(steward.list_candidates(stage="awaiting_review"))
    if candidate_id not in {c.id for c in queue}:
        raise HTTPException(404, "no such review")
    # steward records the key as reviewer; the person goes into its note and our audit row
    decision = await _call(
        steward.decide(
            candidate_id,
            action == "approve",
            user_id=None,
            note=f"{user.username}: {note}" if note else user.username,
        )
    )
    deps: Deps = request.app.state.deps
    async with deps.engine.begin() as conn:
        await conn.execute(
            insert(review_audit).values(
                id=uuid.uuid4(),
                candidate_id=candidate_id,
                user_id=user.id,
                action=action,
                note=note,
            )
        )
    return DecisionOut(
        status=decision.candidate.status,
        entry_status=decision.entry.status if decision.entry else None,
    )


@router.post("/reviews/{candidate_id}/approve")
async def approve(
    candidate_id: str, body: ReviewIn, request: Request, user: Reviewer
) -> DecisionOut:
    return await _review(request, user, candidate_id, "approve", body.note)


@router.post("/reviews/{candidate_id}/reject")
async def reject(
    candidate_id: str, body: ReviewIn, request: Request, user: Reviewer
) -> DecisionOut:
    return await _review(request, user, candidate_id, "reject", body.note)
