"""Conversations, asking a question, and following the agent's steps (design §4, §6)."""

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import asdict
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent
from lite_agent import SessionStore, UnknownSession
from lite_agent.events import Event, RunFinished
from pydantic import BaseModel, Field
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    Numeric,
    Table,
    Text,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncEngine

from glassdesk.agent import build_agent
from glassdesk.auth import CurrentUser
from glassdesk.db import Deps
from glassdesk.runs import Busy, Runs
from glassdesk.steward import Passage
from glassdesk.suggestions import open_cards
from glassdesk.timeline import Answer, Step, changes, project_answer, steps_after
from glassdesk.users import metadata

log = logging.getLogger(__name__)

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
    Column("n", Integer, primary_key=True),  # the citation number, unique in a conversation
    Column("passage", JSONB, nullable=False),
    Column("conversation_id", UUID(as_uuid=True)),
    Column("retrieval_id", Text),  # steward's id for the search: feedback is reported under it
)
run_usage = Table(
    "run_usage",
    metadata,
    Column("run_id", Text, primary_key=True),
    Column("conversation_id", UUID(as_uuid=True), nullable=False),
    Column("user_id", UUID(as_uuid=True), nullable=False),
    Column("finished_at", DateTime(timezone=True), nullable=False),
    Column("input_tokens", Integer),
    Column("output_tokens", Integer),
    Column("cost_usd", Numeric(12, 6)),  # NULL: the endpoint did not say; never 0
    Column("failed", Boolean, nullable=False),
)
answer_feedback = Table(
    "answer_feedback",
    metadata,
    Column("run_id", Text, primary_key=True),
    Column("user_id", UUID(as_uuid=True), primary_key=True),
    Column("helpful", Boolean, nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
)
FAILED_MESSAGE = "这次回答没有完成，请重试。"


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


async def _events(deps: Deps, session_id: str | None, after_seq: int = 0) -> Sequence[Event]:
    if session_id is None or deps.sessions is None:
        return []
    try:
        return await deps.sessions.read(session_id, after_seq=after_seq)
    except UnknownSession:  # asked, but the run has not written its first event yet
        return []


async def _passages(engine: AsyncEngine, conversation_id: uuid.UUID) -> dict[int, Passage]:
    """The conversation's numbered passages: what `[n]` in any of its answers refers to."""
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                select(run_passages.c.n, run_passages.c.passage).where(
                    run_passages.c.conversation_id == conversation_id
                )
            )
        ).all()
    return {r.n: Passage(**r.passage) for r in rows}


async def _next_citation_number(engine: AsyncEngine, conversation_id: uuid.UUID) -> int:
    async with engine.connect() as conn:
        top = await conn.scalar(
            select(func.max(run_passages.c.n)).where(
                run_passages.c.conversation_id == conversation_id
            )
        )
    return (top or 0) + 1


async def _answers(
    engine: AsyncEngine,
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    events: Sequence[Event],
    *,
    last_only: bool = False,
    finished_after: int | None = None,
    run_ids: Sequence[str] | None = None,
) -> list[Answer]:
    """Answers of the finished runs: all, the last only, or those that finished after a seq."""
    runs = [
        e.run_id
        for e in events
        if isinstance(e, RunFinished)
        and (finished_after is None or e.seq > finished_after)
        and (run_ids is None or e.run_id in run_ids)
    ]
    if last_only:
        runs = runs[-1:]
    if not runs:
        return []
    passages = await _passages(engine, conversation_id)
    async with engine.connect() as conn:
        rated = {
            r.run_id: r.helpful
            for r in await conn.execute(
                select(answer_feedback.c.run_id, answer_feedback.c.helpful).where(
                    answer_feedback.c.run_id.in_(runs), answer_feedback.c.user_id == user_id
                )
            )
        }
    answers = (project_answer(events, passages, r) for r in runs)
    return [a.model_copy(update={"feedback": rated.get(a.run_id)}) for a in answers if a]


async def _session_exists(sessions: SessionStore, session_id: str) -> bool:
    try:
        await sessions.read(session_id, upto_seq=1)
    except UnknownSession:
        return False
    return True


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
        run_id = uuid.uuid4().hex
        runs.claim(conv.id, run_id)
    except Busy:
        raise HTTPException(409, "上一个问题还在处理中") from None
    try:
        first = conv.agent_session_id is None
        session_id = conv.agent_session_id or uuid.uuid4().hex
        first_n = await _next_citation_number(deps.engine, conv.id)
        values: dict[str, object] = {"agent_session_id": session_id, "updated_at": func.now()}
        if first:
            values["title"] = body.text.strip()[:TITLE_CHARS] or NEW_TITLE
        async with deps.engine.begin() as conn:
            await conn.execute(
                update(conversations).where(conversations.c.id == conv.id).values(**values)
            )

        async def keep(
            call_id: str, retrieval_id: str, numbered: Sequence[tuple[int, Passage]]
        ) -> None:
            if not numbered:
                return
            async with deps.engine.begin() as conn:
                await conn.execute(
                    insert(run_passages),
                    [
                        {
                            "run_id": run_id,
                            "call_id": call_id,
                            "n": n,
                            "passage": asdict(p),
                            "conversation_id": conv.id,
                            "retrieval_id": retrieval_id,
                        }
                        for n, p in numbered
                    ],
                )

        agent = build_agent(
            model=deps.model,
            sessions=deps.sessions,
            steward=deps.steward,
            user_id=str(user.id),
            brand_name=settings.brand_name,
            on_passages=keep,
            first_n=first_n,
        )
        sessions, steward = deps.sessions, deps.steward
        answered: list[str] = []  # the run's final text, for the episode

        async def work() -> None:
            # From whether the session exists, not from the stored id: a first run that died
            # before writing anything leaves the id behind and no session.
            new = not await _session_exists(sessions, session_id)
            try:
                result = await agent.run(
                    body.text, session_id=session_id, run_id=run_id, new_session=new
                )
            except Exception:
                runs.failed[conv.id] = run_id
                raise
            usage = result.usage
            async with deps.engine.begin() as conn:
                await conn.execute(
                    insert(run_usage).values(
                        run_id=run_id,
                        conversation_id=conv.id,
                        user_id=user.id,
                        finished_at=func.now(),
                        input_tokens=usage.input,
                        output_tokens=usage.output,
                        cost_usd=usage.cost_usd,
                        failed=result.outcome == "failed",
                    )
                )
            # A model failure ends with run_finished (a failed answer); store and harness
            # failures may not have written it.
            if result.error is not None and result.error.kind != "model":
                runs.failed[conv.id] = run_id
            elif result.text:
                answered.append(result.text)

        async def report() -> None:
            """After the claim: steward decides what is worth keeping (a model call on its side),
            and the next question need not wait for that. A failure never touches the answer."""
            if not answered:
                return
            try:
                await steward.report_episode(
                    [("user", body.text), ("assistant", answered[0])],
                    user_id=str(user.id),
                    session_id=session_id,
                )
            except Exception:
                log.warning("reporting the episode of run %s failed", run_id, exc_info=True)

        runs.start(conv.id, run_id, work, after=report)
    except BaseException:
        runs.release(conv.id, run_id)
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
    return await _answers(
        deps.engine, conv.id, conv.user_id, await _events(deps, conv.agent_session_id)
    )


class FeedbackIn(BaseModel):
    helpful: bool


class FeedbackOut(BaseModel):
    helpful: bool


@router.post("/{conversation_id}/answers/{run_id}/feedback")
async def rate_answer(
    run_id: str, body: FeedbackIn, conv: Owned, request: Request, user: CurrentUser
) -> FeedbackOut:
    """The user's verdict on one answer: kept here (one per user, the latest wins) and passed to
    steward for every item the answer cited, best effort."""
    deps = _deps(request)
    events = await _events(deps, conv.agent_session_id)
    found = await _answers(deps.engine, conv.id, conv.user_id, events, run_ids=[run_id])
    if not found:  # not a finished run of this conversation
        raise HTTPException(404, "no such answer")
    answer = found[0]
    async with deps.engine.begin() as conn:
        previous = await conn.scalar(
            select(answer_feedback.c.helpful)
            .where(answer_feedback.c.run_id == run_id, answer_feedback.c.user_id == user.id)
            .with_for_update()
        )
        stmt = pg_insert(answer_feedback).values(
            run_id=run_id, user_id=user.id, helpful=body.helpful
        )
        await conn.execute(
            stmt.on_conflict_do_update(
                index_elements=["run_id", "user_id"],
                set_={"helpful": stmt.excluded.helpful, "updated_at": func.now()},
            )
        )
    if previous == body.helpful:
        # steward flags entries for review from these counts: a repeat must not count again
        return FeedbackOut(helpful=body.helpful)
    if deps.steward is not None and answer.citations:
        async with deps.engine.connect() as conn:
            retrieval_of = {
                r.n: r.retrieval_id
                for r in await conn.execute(
                    select(run_passages.c.n, run_passages.c.retrieval_id).where(
                        run_passages.c.conversation_id == conv.id,
                        run_passages.c.n.in_([c.n for c in answer.citations]),
                    )
                )
            }
        for c in answer.citations:
            if retrieval_of.get(c.n) is None:
                continue
            try:
                await deps.steward.feedback(retrieval_of[c.n], c.item_id, helpful=body.helpful)
            except Exception:
                log.warning("feedback to steward for run %s failed", run_id, exc_info=True)
    return FeedbackOut(helpful=body.helpful)


@router.get("/{conversation_id}/stream", response_class=EventSourceResponse)
async def stream(
    conv: Owned,
    request: Request,
    after: Annotated[int, Query(ge=0)] = 0,
    last_event_id: Annotated[str | None, Header()] = None,
) -> AsyncIterator[ServerSentEvent]:
    """`step` events (id = a cursor to resume after) while a run goes; a run's `answer` as soon
    as it finished (steward may still be reading the episode); then `suggestions` (open cards),
    `failed` for a run that could not finish, and `end`: without it a browser's EventSource
    reconnects when the stream closes."""
    deps, runs = _deps(request), _runs(request)
    cursor = int(last_event_id) if last_event_id and last_event_id.isdigit() else after
    events: list[Event] = []
    answered = False
    while True:
        # read before the events: a run that ends meanwhile is read once more
        going = runs.following(conv.id)
        read_after = events[-1].seq if events else 0
        events.extend(await _events(deps, conv.agent_session_id, read_after))  # only what is new
        start = cursor
        for at, step in changes(events, cursor):
            yield ServerSentEvent(data=step, event="step", id=str(at))
            cursor = at
        # every run that finished since the last read, in order (several after a reconnect)
        for answer in await _answers(
            deps.engine, conv.id, conv.user_id, events, finished_after=start
        ):
            yield ServerSentEvent(data=answer, event="answer")
            answered = True
        if not going:
            break
        await asyncio.sleep(POLL_S)
    failed = runs.failed.get(conv.id)
    if failed is not None and not any(
        isinstance(e, RunFinished) and e.run_id == failed for e in events
    ):
        yield ServerSentEvent(data={"run_id": failed, "message": FAILED_MESSAGE}, event="failed")
    else:
        if not answered:  # attached to a finished conversation: its last answer
            answers = await _answers(deps.engine, conv.id, conv.user_id, events, last_only=True)
            if answers:
                yield ServerSentEvent(data=answers[0], event="answer")
        if deps.steward is not None:
            try:
                cards = await open_cards(deps.steward, str(conv.user_id))
            except Exception:
                log.warning("listing cards failed", exc_info=True)
                cards = []
            if cards:
                yield ServerSentEvent(data=cards, event="suggestions")
    yield ServerSentEvent(data={}, event="end")
