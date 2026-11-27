"""The knowledge page: entries, documents and the review queue (design §4, §5).

Every write is a steward call; what comes back (a live entry or a waiting candidate) is shown as
it is. glassdesk adds the reviewer role and an audit row, since steward sees one API key."""

import uuid
from datetime import datetime
from pathlib import PurePath
from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, Table, Text, func, insert
from sqlalchemy.dialects.postgresql import UUID

from glassdesk.auth import CurrentUser, Reviewer
from glassdesk.db import Deps
from glassdesk.i18n import texts_for
from glassdesk.steward import Candidate, Document, Entry
from glassdesk.users import User, metadata
from glassdesk.web import DecisionOut, Steward

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


def _out[T: BaseModel](model: type[T], value: Entry | Document | Candidate) -> T:
    return model.model_validate(value, from_attributes=True)


def _candidate(c: Candidate | None) -> CandidateOut | None:
    return _out(CandidateOut, c) if c else None


@router.get("/entries")
async def list_entries(steward: Steward, user: CurrentUser) -> list[EntryOut]:
    return [_out(EntryOut, e) for e in await steward.list_entries()]


@router.post("/entries", status_code=201)
async def create_entry(body: EntryIn, steward: Steward, user: CurrentUser) -> WrittenOut:
    written = await steward.create_entry(body.title, body.content, author=user.username)
    return WrittenOut.model_validate(written, from_attributes=True)


@router.get("/documents")
async def list_documents(steward: Steward, user: CurrentUser) -> list[DocumentOut]:
    return [_out(DocumentOut, d) for d in await steward.list_documents()]


@router.post("/documents", status_code=201)
async def upload_document(
    request: Request,
    steward: Steward,
    user: CurrentUser,
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form(max_length=200)] = None,
) -> UploadedOut:
    texts = texts_for(request)
    filename = PurePath(file.filename or "").name
    if PurePath(filename).suffix.lower() not in UPLOAD_TYPES:
        raise HTTPException(422, texts.upload_types)
    if file.size is not None and file.size > MAX_UPLOAD_BYTES:  # known before reading
        raise HTTPException(422, texts.upload_too_big)
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if not data:
        raise HTTPException(422, texts.upload_empty)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(422, texts.upload_too_big)
    mime = file.content_type or "application/octet-stream"
    document, candidate = await steward.upload_document(filename, data, mime, title=title or None)
    return UploadedOut(document=_out(DocumentOut, document), candidate=_candidate(candidate))


@router.get("/reviews")
async def list_reviews(steward: Steward, user: Reviewer) -> list[CandidateOut]:
    return [_out(CandidateOut, c) for c in await steward.list_candidates(stage="awaiting_review")]


async def _review(
    request: Request,
    steward: Steward,
    user: User,
    candidate_id: str,
    action: Literal["approve", "reject"],
    note: str | None,
) -> DecisionOut:
    # Only what is in the review queue: the key may decide any candidate, including another
    # user's open card, so the queue is the reviewer's whole reach.
    queue = await steward.list_candidates(stage="awaiting_review")
    if candidate_id not in {c.id for c in queue}:
        raise HTTPException(404, "no such review")
    # steward records the key as reviewer; the person goes into its note and our audit row
    decision = await steward.decide(
        candidate_id,
        action == "approve",
        user_id=None,
        note=f"{user.username}: {note}" if note else user.username,
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
    return DecisionOut.of(decision)


@router.post("/reviews/{candidate_id}/approve")
async def approve(
    candidate_id: str, body: ReviewIn, request: Request, steward: Steward, user: Reviewer
) -> DecisionOut:
    return await _review(request, steward, user, candidate_id, "approve", body.note)


@router.post("/reviews/{candidate_id}/reject")
async def reject(
    candidate_id: str, body: ReviewIn, request: Request, steward: Steward, user: Reviewer
) -> DecisionOut:
    return await _review(request, steward, user, candidate_id, "reject", body.note)
