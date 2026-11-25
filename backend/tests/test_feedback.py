from collections.abc import Callable

from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from glassdesk.testing import FakeSteward
from glassdesk.users import create_user
from tests.helpers import P1, ask, client_for, search_then_answer


async def answered(client, text_: str = "报销上限？") -> tuple[str, str]:  # type: ignore[no-untyped-def]
    conv_id, run_id = await ask(client, text_)
    await client.get(f"/api/conversations/{conv_id}/stream")
    return conv_id, run_id


async def test_changing_a_rating_keeps_one_row_and_tells_steward_only_the_first(
    make_app: Callable[..., FastAPI], engine: AsyncEngine
) -> None:
    steward = FakeSteward([P1])
    client = await client_for(make_app(search_then_answer("800 元[1]"), steward), engine, "alice")
    conv_id, run_id = await answered(client)
    url = f"/api/conversations/{conv_id}/answers/{run_id}/feedback"
    assert (await client.post(url, json={"helpful": True})).json() == {"helpful": True}
    assert (await client.post(url, json={"helpful": False})).json() == {"helpful": False}
    async with engine.connect() as conn:
        rows = (await conn.execute(text("select helpful from answer_feedback"))).all()
    assert [r.helpful for r in rows] == [False]
    # steward adds every verdict it hears: a flip would count the same person twice
    assert steward.feedbacks == [("fake-1", "e1", True)]
    [answer] = (await client.get(f"/api/conversations/{conv_id}/answers")).json()
    assert answer["feedback"] is False


async def test_only_the_owner_rates_and_only_a_real_answer(
    make_app: Callable[..., FastAPI], engine: AsyncEngine
) -> None:
    app = make_app(search_then_answer("800 元[1]"), FakeSteward([P1]))
    alice = await client_for(app, engine, "alice")
    bob = await client_for(app, engine, "bob")
    conv_id, run_id = await answered(alice)
    other = await bob.post(
        f"/api/conversations/{conv_id}/answers/{run_id}/feedback", json={"helpful": True}
    )
    unknown = await alice.post(
        f"/api/conversations/{conv_id}/answers/not-a-run/feedback", json={"helpful": True}
    )
    assert (other.status_code, unknown.status_code) == (404, 404)


async def test_a_rating_is_kept_when_steward_is_down(
    make_app: Callable[..., FastAPI], engine: AsyncEngine
) -> None:
    steward = FakeSteward([P1])
    client = await client_for(make_app(search_then_answer("800 元[1]"), steward), engine, "alice")
    conv_id, run_id = await answered(client)
    steward.fail = True
    response = await client.post(
        f"/api/conversations/{conv_id}/answers/{run_id}/feedback", json={"helpful": True}
    )
    assert response.status_code == 200


async def test_every_run_records_its_usage(
    make_app: Callable[..., FastAPI], engine: AsyncEngine
) -> None:
    client = await client_for(
        make_app(search_then_answer("a[1]"), FakeSteward([P1])), engine, "alice"
    )
    conv_id, run_id = await answered(client)
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text("select run_id, conversation_id::text, failed, cost_usd from run_usage")
            )
        ).all()
    assert [(r.run_id, r.conversation_id, r.failed, r.cost_usd) for r in rows] == [
        (run_id, conv_id, False, None)
    ]


async def test_repeating_the_same_rating_tells_steward_once(
    make_app: Callable[..., FastAPI], engine: AsyncEngine
) -> None:
    """steward flags entries for review from these counts: a rating resent many times must not
    count many times."""
    steward = FakeSteward([P1])
    client = await client_for(make_app(search_then_answer("800 元[1]"), steward), engine, "alice")
    conv_id, run_id = await answered(client)
    url = f"/api/conversations/{conv_id}/answers/{run_id}/feedback"
    for _ in range(5):
        assert (await client.post(url, json={"helpful": False})).status_code == 200
    assert steward.feedbacks == [("fake-1", "e1", False)]


async def test_a_run_that_raises_is_counted_as_failed(
    make_app: Callable[..., FastAPI],
    engine: AsyncEngine,
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    """Insights count failures from run_usage: a run that never returned (lite-agent raises,
    e.g. a crash mid-tool left calls unresolved) must be there too."""
    from lite_agent import UnresolvedCalls

    import glassdesk.conversations as conversations

    class Raising:
        async def run(self, *a: object, **k: object) -> None:
            raise UnresolvedCalls("s", ("c1",))

    monkeypatch.setattr(conversations, "build_agent", lambda **k: Raising())
    client = await client_for(make_app(search_then_answer("a"), FakeSteward([P1])), engine, "alice")
    _conv_id, run_id = await answered(client)
    async with engine.connect() as conn:
        rows = (await conn.execute(text("select run_id, failed from run_usage"))).all()
    assert [(r.run_id, r.failed) for r in rows] == [(run_id, True)]


async def test_two_first_ratings_at_once_tell_steward_once(
    make_app: Callable[..., FastAPI], engine: AsyncEngine
) -> None:
    """A double click or two tabs: both requests find no earlier rating."""
    import asyncio

    steward = FakeSteward([P1])
    client = await client_for(make_app(search_then_answer("800 元[1]"), steward), engine, "alice")
    conv_id, run_id = await answered(client)
    url = f"/api/conversations/{conv_id}/answers/{run_id}/feedback"
    responses = await asyncio.gather(*(client.post(url, json={"helpful": False}) for _ in range(4)))
    assert [r.status_code for r in responses] == [200] * 4
    assert steward.feedbacks == [("fake-1", "e1", False)]


async def test_save_rating_says_changed_once_when_two_first_ratings_race(
    engine: AsyncEngine,
) -> None:
    """Two transactions rate the same answer for the first time at once: only one of them may
    report a change (only that one is sent to steward)."""
    import asyncio

    from glassdesk.conversations import save_rating

    user = await create_user(engine, "alice", "pw", "member")
    async with engine.connect() as a, engine.connect() as b:
        await a.begin()
        await b.begin()
        first = await save_rating(a, "run-1", user.id, False)  # inserted, not committed yet
        second = asyncio.create_task(save_rating(b, "run-1", user.id, False))  # waits on a's row
        await asyncio.sleep(0.2)
        await a.commit()
        second_changed = await second
        await b.commit()
    assert (first, second_changed) == (True, False)


async def test_flipping_back_and_forth_tells_steward_once(
    make_app: Callable[..., FastAPI], engine: AsyncEngine
) -> None:
    steward = FakeSteward([P1])
    client = await client_for(make_app(search_then_answer("800 元[1]"), steward), engine, "alice")
    conv_id, run_id = await answered(client)
    url = f"/api/conversations/{conv_id}/answers/{run_id}/feedback"
    for helpful in (False, True, False, True, False):
        assert (await client.post(url, json={"helpful": helpful})).json() == {"helpful": helpful}
    assert steward.feedbacks == [("fake-1", "e1", False)]
