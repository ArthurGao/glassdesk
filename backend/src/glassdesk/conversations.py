"""Conversations, asking a question, and following the agent's steps (design §4, §6)."""

import asyncio
import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import asdict
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent
from lite_agent import UnknownSession
from lite_agent.events import Event, RunFinished
from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, Integer, Table, Text, func, insert, select, update
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncEngine

from glassdesk.agent import build_agent
from glassdesk.auth import CurrentUser
from glassdesk.db import Deps
from glassdesk.runs import Busy, Runs
from glassdesk.steward import Passage
from glassdesk.timeline import Answer, Step, changes, project_answer, steps_after
from glassdesk.users import metadata

POLL_S = 0.25
NEW_TITLE = "新会话"
TITLE_CHARS = 30

conversations = Table(
    "conversations",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("user_id", UUID(as_uuid=True), nullable=False),
    Column("agent_session_id", Text),
    Column("title", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
)
run_passages = Table(
    "run_passages",
    metadata,
    Column("run_id", Text, primary_key=True),
    Column("call_id", Text, primary_key=True),
    Column("n", Integer, primary_key=True),
    Column("passage", JSONB, nullable=False),
)


class ConversationOut(BaseModel):
    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class RunOut(BaseModel):
    run_id: str


router = APIRouter(prefix="/api/conversations")


def _deps(request: Request) -> Deps:
    deps: Deps = request.app.state.deps
    return deps


def _runs(request: Request) -> Runs:
    runs: Runs = request.app.state.runs
    return runs


async def _owned(
    conversation_id: uuid.UUID, request: Request, user: CurrentUser
) -> "Row[tuple[object, ...]]":
    """The user's conversation; someone else's is 404, so its existence is not confirmed. A
    dependency, so the 404 is decided before a stream opens."""
    async with _deps(request).engine.connect() as conn:
        row = (
            await conn.execute(
                select(conversations).where(
                    conversations.c.id == conversation_id, conversations.c.user_id == user.id
                )
            )
        ).first()
    if row is None:
        raise HTTPException(404, "no such conversation")
    return row


Owned = Annotated["Row[tuple[object, ...]]", Depends(_owned)]


async def _events(deps: Deps, session_id: str | None) -> Sequence[Event]:
    if session_id is None or deps.sessions is None:
        return []
    try:
        return await deps.sessions.read(session_id)
    except UnknownSession:  # asked, but the run has not written its first event yet
        return []


async def _passages(engine: AsyncEngine, run_ids: Sequence[str]) -> dict[str, list[Passage]]:
    if not run_ids:
        return {}
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                select(run_passages)
                .where(run_passages.c.run_id.in_(run_ids))
                .order_by(run_passages.c.call_id, run_passages.c.n)
            )
        ).all()
    out: dict[str, list[Passage]] = {}
    for r in rows:
        out.setdefault(r.call_id, []).append(Passage(**r.passage))
    return out


def _finished_runs(events: Sequence[Event]) -> list[str]:
    return [e.run_id for e in events if isinstance(e, RunFinished)]


async def _answers(engine: AsyncEngine, events: Sequence[Event]) -> list[Answer]:
    runs = _finished_runs(events)
    passages = await _passages(engine, runs)
    answers = (project_answer(events, passages, r) for r in runs)
    return [a for a in answers if a is not None]


@router.post("", status_code=201)
async def create_conversation(request: Request, user: CurrentUser) -> ConversationOut:
    async with _deps(request).engine.begin() as conn:
        row = (
            await conn.execute(
                insert(conversations)
                .values(id=uuid.uuid4(), user_id=user.id, title=NEW_TITLE)
                .returning(conversations)
            )
        ).one()
    return ConversationOut.model_validate(row, from_attributes=True)


@router.get("")
async def list_conversations(request: Request, user: CurrentUser) -> list[ConversationOut]:
    async with _deps(request).engine.connect() as conn:
        rows = (
            await conn.execute(
                select(conversations)
                .where(conversations.c.user_id == user.id)
                .order_by(conversations.c.updated_at.desc())
            )
        ).all()
    return [ConversationOut.model_validate(r, from_attributes=True) for r in rows]


@router.post("/{conversation_id}/messages", status_code=202)
async def ask(body: MessageIn, conv: Owned, request: Request, user: CurrentUser) -> RunOut:
    deps, runs, settings = _deps(request), _runs(request), request.app.state.settings
    if deps.model is None or deps.sessions is None or deps.steward is None:
        raise HTTPException(503, "模型或知识库未配置")
    try:
        runs.claim(conv.id)
    except Busy:
        raise HTTPException(409, "上一个问题还在处理中") from None
    try:
        first = conv.agent_session_id is None
        session_id = conv.agent_session_id or uuid.uuid4().hex
        run_id = uuid.uuid4().hex
        values: dict[str, object] = {"agent_session_id": session_id, "updated_at": func.now()}
        if first:
            values["title"] = body.text.strip()[:TITLE_CHARS] or NEW_TITLE
        async with deps.engine.begin() as conn:
            await conn.execute(
                update(conversations).where(conversations.c.id == conv.id).values(**values)
            )

        async def keep(call_id: str, passages: Sequence[Passage]) -> None:
            if not passages:
                return
            async with deps.engine.begin() as conn:
                await conn.execute(
                    insert(run_passages),
                    [
                        {"run_id": run_id, "call_id": call_id, "n": n, "passage": asdict(p)}
                        for n, p in enumerate(passages, start=1)
                    ],
                )

        agent = build_agent(
            model=deps.model,
            sessions=deps.sessions,
            steward=deps.steward,
            user_id=str(user.id),
            brand_name=settings.brand_name,
            on_passages=keep,
        )

        async def work() -> None:
            await agent.run(body.text, session_id=session_id, run_id=run_id, new_session=first)

        runs.start(conv.id, work)
    except BaseException:
        runs.release(conv.id)
        raise
    return RunOut(run_id=run_id)


@router.get("/{conversation_id}/steps")
async def get_steps(
    conv: Owned, request: Request, after: Annotated[int, Query(ge=0)] = 0
) -> list[Step]:
    deps = _deps(request)
    return steps_after(await _events(deps, conv.agent_session_id), after)


@router.get("/{conversation_id}/answers")
async def get_answers(conv: Owned, request: Request) -> list[Answer]:
    deps = _deps(request)
    return await _answers(deps.engine, await _events(deps, conv.agent_session_id))


@router.get("/{conversation_id}/stream", response_class=EventSourceResponse)
async def stream(
    conv: Owned,
    request: Request,
    after: Annotated[int, Query(ge=0)] = 0,
    last_event_id: Annotated[str | None, Header()] = None,
) -> AsyncIterator[ServerSentEvent]:
    """`step` events (id = a cursor to resume after) while a run goes, then the last `answer`,
    then `end`: without it a browser's EventSource reconnects when the stream closes."""
    deps, runs = _deps(request), _runs(request)
    cursor = int(last_event_id) if last_event_id and last_event_id.isdigit() else after
    while True:
        going = runs.busy(
            conv.id
        )  # read before the events: a run that ends meanwhile is read once more
        events = await _events(deps, conv.agent_session_id)
        for at, step in changes(events, cursor):
            yield ServerSentEvent(data=step, event="step", id=str(at))
            cursor = at
        if not going:
            break
        await asyncio.sleep(POLL_S)
    answers = await _answers(deps.engine, events)
    if answers:
        yield ServerSentEvent(data=answers[-1], event="answer")
    yield ServerSentEvent(data={}, event="end")
