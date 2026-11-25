from collections.abc import Callable

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from glassdesk.testing import FakeSteward
from tests.helpers import P1, ask, client_for, parse_sse, search_then_answer


async def test_a_card_from_the_episode_follows_the_answer(
    make_app: Callable[..., FastAPI], engine: AsyncEngine
) -> None:
    steward = FakeSteward([P1])
    client = await client_for(make_app(search_then_answer("好的[1]"), steward), engine, "alice")
    conv_id, _ = await ask(client, "记住：报销要在 30 天内提交")
    messages = parse_sse((await client.get(f"/api/conversations/{conv_id}/stream")).text)
    assert [m[0] for m in messages[-3:]] == ["answer", "suggestions", "end"]
    [card] = messages[-2][2]
    assert card["title"] == "报销要在 30 天内提交"
    assert set(card) == {"id", "title", "content", "risk_level", "reason"}
    listed = (await client.get("/api/suggestions")).json()
    assert [c["id"] for c in listed] == [card["id"]]


async def test_steward_down_while_reporting_still_answers(
    make_app: Callable[..., FastAPI], engine: AsyncEngine
) -> None:
    class DownForEpisodes(FakeSteward):
        async def report_episode(self, *a: object, **k: object) -> list:  # type: ignore[type-arg]
            from glassdesk.steward import StewardUnavailable

            raise StewardUnavailable("ConnectError")

        async def list_candidates(self, *a: object, **k: object) -> list:  # type: ignore[type-arg]
            from glassdesk.steward import StewardUnavailable

            raise StewardUnavailable("ConnectError")

    app = make_app(search_then_answer("好的[1]"), DownForEpisodes([P1]))
    client = await client_for(app, engine, "alice")
    conv_id, _ = await ask(client, "记住：x")
    messages = parse_sse((await client.get(f"/api/conversations/{conv_id}/stream")).text)
    assert [m[0] for m in messages[-2:]] == ["answer", "end"]
    assert messages[-2][2]["text"] == "好的[1]"


async def test_accepting_as_team_makes_an_entry_and_a_second_decision_is_409(
    make_app: Callable[..., FastAPI], engine: AsyncEngine
) -> None:
    steward = FakeSteward([P1])
    client = await client_for(make_app(search_then_answer("好"), steward), engine, "alice")
    conv_id, _ = await ask(client, "记住：周五下午不开会")
    await client.get(f"/api/conversations/{conv_id}/stream")
    [card] = (await client.get("/api/suggestions")).json()
    accepted = await client.post(f"/api/suggestions/{card['id']}/accept", json={"scope": "team"})
    assert accepted.status_code == 200
    assert accepted.json() == {"status": "accepted", "entry_status": "active"}
    assert [e.title for e in steward.entries] == ["周五下午不开会"]
    again = await client.post(f"/api/suggestions/{card['id']}/accept", json={"scope": "team"})
    assert again.status_code == 404  # no longer an open card of this user
    assert (await client.get("/api/suggestions")).json() == []


async def test_rejecting_removes_the_card(
    make_app: Callable[..., FastAPI], engine: AsyncEngine
) -> None:
    client = await client_for(
        make_app(search_then_answer("好"), FakeSteward([P1])), engine, "alice"
    )
    conv_id, _ = await ask(client, "记住：x")
    await client.get(f"/api/conversations/{conv_id}/stream")
    [card] = (await client.get("/api/suggestions")).json()
    rejected = await client.post(f"/api/suggestions/{card['id']}/reject")
    assert rejected.json() == {"status": "rejected", "entry_status": None}
    assert (await client.get("/api/suggestions")).json() == []


async def test_another_users_card_is_404_and_never_decided(
    make_app: Callable[..., FastAPI], engine: AsyncEngine
) -> None:
    steward = FakeSteward([P1])
    app = make_app(search_then_answer("好"), steward)
    alice = await client_for(app, engine, "alice")
    bob = await client_for(app, engine, "bob")
    conv_id, _ = await ask(alice, "记住：x")
    await alice.get(f"/api/conversations/{conv_id}/stream")
    [card] = (await alice.get("/api/suggestions")).json()
    for action in ("accept", "reject"):
        response = await bob.post(f"/api/suggestions/{card['id']}/{action}", json={"scope": "team"})
        assert response.status_code == 404
    assert [c.status for c in steward.candidates] == ["pending"]


async def test_a_conflict_from_steward_is_409(
    make_app: Callable[..., FastAPI], engine: AsyncEngine
) -> None:
    """Two tabs: the card is still listed, but steward already has a decision for it."""
    from glassdesk.steward import Decision, StewardRejected

    class Raced(FakeSteward):
        async def decide(self, *a: object, **k: object) -> Decision:
            raise StewardRejected(409, "already decided")

    client = await client_for(make_app(search_then_answer("好"), Raced([P1])), engine, "alice")
    conv_id, _ = await ask(client, "记住：x")
    await client.get(f"/api/conversations/{conv_id}/stream")
    [card] = (await client.get("/api/suggestions")).json()
    response = await client.post(f"/api/suggestions/{card['id']}/accept", json={"scope": "team"})
    assert (response.status_code, response.json()["detail"]) == (409, "已处理")
