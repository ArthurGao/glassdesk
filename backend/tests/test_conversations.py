import asyncio
from collections.abc import AsyncIterator, Callable

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from lite_agent.pg import PgSessionStore
from sqlalchemy.ext.asyncio import AsyncEngine

from glassdesk.app import create_app
from glassdesk.config import Settings
from glassdesk.db import Deps
from glassdesk.testing import FakeSteward
from glassdesk.users import create_user
from tests.conftest import TEST_AGENT_SCHEMA, _test_url
from tests.helpers import P1, BlockingModel, login, parse_sse, search_then_answer


@pytest.fixture
async def sessions() -> AsyncIterator[PgSessionStore]:
    store = PgSessionStore(_test_url().replace("+psycopg", ""), schema=TEST_AGENT_SCHEMA)
    yield store
    await store.close()


@pytest.fixture
def make_app(
    settings: Settings, engine: AsyncEngine, sessions: PgSessionStore
) -> Callable[..., FastAPI]:
    def make(model: object, steward: FakeSteward | None = None) -> FastAPI:
        deps = Deps(
            engine=engine,
            model=model,
            sessions=sessions,  # type: ignore[arg-type]
            steward=steward or FakeSteward([P1]),
        )
        return create_app(settings, deps=deps)

    return make


async def client_for(app: FastAPI, engine: AsyncEngine, username: str) -> AsyncClient:
    await create_user(engine, username, "pw", "member")
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    await login(client, username)
    return client


async def ask(client: AsyncClient, text: str = "报销上限是多少？") -> tuple[str, str]:
    conv = (await client.post("/api/conversations")).json()
    response = await client.post(f"/api/conversations/{conv['id']}/messages", json={"text": text})
    assert response.status_code == 202
    return conv["id"], response.json()["run_id"]


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
