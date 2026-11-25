import asyncio
from collections.abc import Callable

from fastapi import FastAPI
from lite_agent.pg import PgSessionStore
from sqlalchemy.ext.asyncio import AsyncEngine

from glassdesk.app import create_app
from glassdesk.config import Settings
from glassdesk.db import Deps
from glassdesk.testing import FakeSteward
from tests.helpers import P1, BlockingModel, ask, client_for, parse_sse, search_then_answer


async def test_ask_streams_steps_then_answer(
    make_app: Callable[..., FastAPI], engine: AsyncEngine
) -> None:
    client = await client_for(make_app(search_then_answer("上限每晚 800 元[1]。")), engine, "alice")
    conv_id, run_id = await ask(client)
    body = (await client.get(f"/api/conversations/{conv_id}/stream")).text
    messages = parse_sse(body)
    kinds = [m[0] for m in messages]
    # the stream ends with the answer, then `end` so the browser does not reconnect
    assert kinds[-2:] == ["answer", "end"] and set(kinds[:-2]) == {"step"}
    assert [m[2]["kind"] for m in messages[:-2]] == [
        "question",
        "thinking",
        "tool",
        "answer",
        "finished",
    ]
    answer = messages[-2][2]
    assert answer["run_id"] == run_id
    assert answer["question"] == "报销上限是多少？"
    assert answer["text"] == "上限每晚 800 元[1]。"
    assert [(c["n"], c["item_id"]) for c in answer["citations"]] == [(1, "e1")]
    listed = (await client.get("/api/conversations")).json()
    assert [c["title"] for c in listed] == ["报销上限是多少？"]
    assert (await client.get(f"/api/conversations/{conv_id}/answers")).json() == [answer]


async def test_second_message_while_running_is_409(
    make_app: Callable[..., FastAPI], engine: AsyncEngine
) -> None:
    model = BlockingModel(search_then_answer("a[1]", "b"))
    client = await client_for(make_app(model), engine, "alice")
    conv_id, _ = await ask(client)
    again = await client.post(f"/api/conversations/{conv_id}/messages", json={"text": "再问"})
    assert again.status_code == 409
    model.release.set()
    await client.get(f"/api/conversations/{conv_id}/stream")  # waits for the run to end
    after = await client.post(f"/api/conversations/{conv_id}/messages", json={"text": "再问"})
    assert after.status_code == 202
    await client.get(f"/api/conversations/{conv_id}/stream")


async def test_other_users_conversation_is_404(
    make_app: Callable[..., FastAPI], engine: AsyncEngine
) -> None:
    app = make_app(search_then_answer("a"))
    alice = await client_for(app, engine, "alice")
    bob = await client_for(app, engine, "bob")
    conv_id, _ = await ask(alice)
    await alice.get(f"/api/conversations/{conv_id}/stream")
    base = f"/api/conversations/{conv_id}"
    assert (await bob.post(f"{base}/messages", json={"text": "x"})).status_code == 404
    for path in ("/steps", "/stream", "/answers"):
        assert (await bob.get(base + path)).status_code == 404
    assert (await bob.get("/api/conversations")).json() == []


async def test_stream_resumes_from_last_event_id_without_duplicates(
    make_app: Callable[..., FastAPI], engine: AsyncEngine
) -> None:
    client = await client_for(make_app(search_then_answer("a[1]")), engine, "alice")
    conv_id, _ = await ask(client)
    full = parse_sse((await client.get(f"/api/conversations/{conv_id}/stream")).text)
    steps = [m for m in full if m[0] == "step"]
    cut = next(i for i, m in enumerate(steps) if m[2]["kind"] == "tool")
    resumed = parse_sse(
        (
            await client.get(
                f"/api/conversations/{conv_id}/stream",
                headers={"Last-Event-ID": str(steps[cut][1])},
            )
        ).text
    )
    seen = [m[2]["seq"] for m in steps[: cut + 1]] + [
        m[2]["seq"] for m in resumed if m[0] == "step"
    ]
    assert seen == [m[2]["seq"] for m in steps]
    assert [m[0] for m in resumed[-2:]] == ["answer", "end"]


async def test_steward_down_run_finishes_with_error_step(
    make_app: Callable[..., FastAPI], engine: AsyncEngine
) -> None:
    app = make_app(search_then_answer("知识库暂时不可用。"), FakeSteward(fail=True))
    client = await client_for(app, engine, "alice")
    conv_id, _ = await ask(client)
    messages = parse_sse((await client.get(f"/api/conversations/{conv_id}/stream")).text)
    tool = next(m[2] for m in messages if m[0] == "step" and m[2]["kind"] == "tool")
    assert tool["status"] == "error"
    assert [m[0] for m in messages[-2:]] == ["answer", "end"]
    assert messages[-2][2]["citations"] == []


async def test_empty_or_too_long_text_is_422(
    make_app: Callable[..., FastAPI], engine: AsyncEngine
) -> None:
    client = await client_for(make_app(search_then_answer("a")), engine, "alice")
    conv = (await client.post("/api/conversations")).json()
    for text in ("", "x" * 4001):
        response = await client.post(
            f"/api/conversations/{conv['id']}/messages", json={"text": text}
        )
        assert response.status_code == 422
    await asyncio.sleep(0)


async def test_a_stream_with_nothing_running_ends_at_once(
    make_app: Callable[..., FastAPI], engine: AsyncEngine
) -> None:
    client = await client_for(make_app(search_then_answer("a")), engine, "alice")
    conv = (await client.post("/api/conversations")).json()
    messages = parse_sse((await client.get(f"/api/conversations/{conv['id']}/stream")).text)
    assert [m[0] for m in messages] == ["end"]


async def test_runs_that_reuse_a_call_id_keep_their_own_citations(
    make_app: Callable[..., FastAPI], engine: AsyncEngine
) -> None:
    """Some endpoints number tool calls per turn (call_0, …): ids repeat across runs."""
    from lite_model import AssistantTurn, Text, ToolCall
    from lite_model.testing import AsyncFakeModel

    from glassdesk.agent import ROLE
    from glassdesk.steward import Passage

    def same_id_run(answer: str) -> list[AssistantTurn]:
        return [
            AssistantTurn((ToolCall("call_0", "search_knowledge", {"query": "q"}),)),
            AssistantTurn((Text(answer),)),
        ]

    model = AsyncFakeModel(**{ROLE: [*same_id_run("一[1]"), *same_id_run("二[2]")]})
    steward = FakeSteward([P1])
    client = await client_for(make_app(model, steward), engine, "alice")
    conv_id, _ = await ask(client, "第一问")
    await client.get(f"/api/conversations/{conv_id}/stream")
    steward.passages = (
        Passage(
            item_id="e2",
            kind="entry",
            title="第二份",
            source="kb",
            text="t2",
            score=0.7,
            verified=False,
        ),
    )
    await client.post(f"/api/conversations/{conv_id}/messages", json={"text": "第二问"})
    await client.get(f"/api/conversations/{conv_id}/stream")
    answers = (await client.get(f"/api/conversations/{conv_id}/answers")).json()
    assert [[c["item_id"] for c in a["citations"]] for a in answers] == [["e1"], ["e2"]]


async def test_citations_number_continuously_across_searches(
    make_app: Callable[..., FastAPI], engine: AsyncEngine
) -> None:
    """Two searches in one run: [3] is the second search's first passage, not unmatched,
    and [2] is the first search's second passage, never another search's."""
    from lite_model import AssistantTurn, Text, ToolCall
    from lite_model.testing import AsyncFakeModel

    from glassdesk.agent import ROLE
    from glassdesk.steward import Passage

    p2 = Passage(
        item_id="e2", kind="entry", title="T2", source="kb", text="t2", score=0.5, verified=False
    )
    model = AsyncFakeModel(
        **{
            ROLE: [
                AssistantTurn((ToolCall("a", "search_knowledge", {"query": "q1"}),)),
                AssistantTurn((ToolCall("b", "search_knowledge", {"query": "q2"}),)),
                AssistantTurn((Text("x[2] y[3] z[9]"),)),
            ]
        }
    )
    client = await client_for(make_app(model, FakeSteward([P1, p2])), engine, "alice")
    conv_id, _ = await ask(client)
    messages = parse_sse((await client.get(f"/api/conversations/{conv_id}/stream")).text)
    answer = next(m[2] for m in messages if m[0] == "answer")
    assert [(c["n"], c["item_id"]) for c in answer["citations"]] == [(2, "e2"), (3, "e1")]
    assert answer["unmatched"] == [9]


async def test_a_session_that_was_never_written_is_started_on_the_next_ask(
    make_app: Callable[..., FastAPI], engine: AsyncEngine
) -> None:
    """The first run died before writing anything: the id is stored, the session is not."""
    from sqlalchemy import text

    client = await client_for(make_app(search_then_answer("a[1]")), engine, "alice")
    conv = (await client.post("/api/conversations")).json()
    async with engine.begin() as conn:
        await conn.execute(
            text("update conversations set agent_session_id = 'never-written' where id = :id"),
            {"id": conv["id"]},
        )
    await client.post(f"/api/conversations/{conv['id']}/messages", json={"text": "q"})
    messages = parse_sse((await client.get(f"/api/conversations/{conv['id']}/stream")).text)
    assert [m[0] for m in messages[-2:]] == ["answer", "end"]


class _BrokenStore:
    """A session store whose writes fail, as when the database goes away mid-run."""

    def __init__(self, inner: PgSessionStore) -> None:
        self.inner = inner

    async def append(self, *args: object, **kwargs: object) -> None:
        from lite_agent import StoreError

        raise StoreError("database went away")

    def __getattr__(self, name: str) -> object:
        return getattr(self.inner, name)


async def test_a_run_that_could_not_finish_is_reported_on_the_stream(
    settings: Settings, engine: AsyncEngine, sessions: PgSessionStore
) -> None:
    deps = Deps(
        engine=engine,
        model=search_then_answer("a"),
        sessions=_BrokenStore(sessions),  # type: ignore[arg-type]
        steward=FakeSteward([P1]),
    )
    client = await client_for(create_app(settings, deps=deps), engine, "alice")
    conv_id, run_id = await ask(client)
    messages = parse_sse((await client.get(f"/api/conversations/{conv_id}/stream")).text)
    assert [m[0] for m in messages] == ["failed", "end"]
    assert messages[0][2] == {"run_id": run_id, "message": "这次回答没有完成，请重试。"}
