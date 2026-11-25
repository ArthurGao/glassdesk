import json
import uuid

import httpx
import pytest
import respx

from glassdesk.steward import HttpSteward, StewardRejected
from glassdesk.testing import FakeSteward
from tests.test_steward_kb import BASE, COL, candidate_json, collections, entry_json


@pytest.fixture
def steward() -> HttpSteward:
    return HttpSteward(BASE, "stw_k", collection="company", timeout_s=0.2)


def _collections() -> None:
    respx.get(f"{BASE}/v1/kb/collections").mock(
        return_value=httpx.Response(200, json=collections("company"))
    )


@respx.mock
async def test_report_episode_sends_messages_sync_and_returns_cards(steward: HttpSteward) -> None:
    card = candidate_json(
        stage="awaiting_user",
        risk_level="medium",
        requested_for_user="u1",
        origin="extraction",
        draft={"title": "报销时限", "content": "30 天"},
    )
    route = respx.post(f"{BASE}/v1/episodes").mock(
        return_value=httpx.Response(
            200,
            json={
                "episode_id": str(uuid.uuid4()),
                "status": "processed",
                "job_id": None,
                "memories": [],
                "suggestions": [card],
            },
        )
    )
    cards = await steward.report_episode(
        [("user", "报销多久？"), ("assistant", "30 天内[1]")], user_id="u1", session_id="s1"
    )
    assert [(c.id, c.stage, c.title) for c in cards] == [(card["id"], "awaiting_user", "报销时限")]
    body = json.loads(route.calls[0].request.content)
    assert body["mode"] == "sync"
    assert body["messages"] == [
        {"role": "user", "content": "报销多久？"},
        {"role": "assistant", "content": "30 天内[1]"},
    ]
    assert (body["user_id"], body["session_id"]) == ("u1", "s1")


@respx.mock
async def test_suggest_sends_collection_user_and_session(steward: HttpSteward) -> None:
    _collections()
    card = candidate_json(stage="awaiting_user", requested_for_user="u1", origin="user_suggestion")
    route = respx.post(f"{BASE}/v1/suggestions").mock(
        return_value=httpx.Response(201, json={"entry": None, "candidate": card})
    )
    written = await steward.suggest("报销时限\n30 天", user_id="u1", session_id="s1")
    assert written.candidate is not None and written.candidate.stage == "awaiting_user"
    body = json.loads(route.calls[0].request.content)
    assert body == {
        "collection_id": COL,
        "text": "报销时限\n30 天",
        "user_id": "u1",
        "session_id": "s1",
    }


@respx.mock
async def test_list_candidates_filters_by_stage_and_user(steward: HttpSteward) -> None:
    route = respx.get(f"{BASE}/v1/candidates").mock(
        return_value=httpx.Response(200, json={"items": [candidate_json()], "next_cursor": None})
    )
    assert len(await steward.list_candidates(stage="awaiting_user", user_id="u1")) == 1
    params = route.calls[0].request.url.params
    assert (params["stage"], params["user_id"], params["status"]) == (
        "awaiting_user",
        "u1",
        "pending",
    )


@respx.mock
async def test_a_card_decision_names_the_user_and_a_review_does_not(steward: HttpSteward) -> None:
    cid = str(uuid.uuid4())
    decided = candidate_json(id=cid, status="accepted") | {"entry": entry_json()}
    accept = respx.post(f"{BASE}/v1/candidates/{cid}/accept").mock(
        return_value=httpx.Response(200, json=decided)
    )
    reject = respx.post(f"{BASE}/v1/candidates/{cid}/reject").mock(
        return_value=httpx.Response(
            200, json=candidate_json(id=cid, status="rejected") | {"entry": None}
        )
    )
    card = await steward.decide(cid, True, user_id="u1", scope="team")
    assert card.candidate.status == "accepted" and card.entry is not None
    assert json.loads(accept.calls[0].request.content) == {"user_id": "u1", "scope": "team"}
    review = await steward.decide(cid, False, user_id=None, note="alice: 不准确")
    assert review.entry is None
    assert json.loads(reject.calls[0].request.content) == {"note": "alice: 不准确"}


@respx.mock
async def test_deciding_twice_is_rejected_409(steward: HttpSteward) -> None:
    cid = str(uuid.uuid4())
    respx.post(f"{BASE}/v1/candidates/{cid}/accept").mock(
        return_value=httpx.Response(
            409, json={"status": 409, "code": "conflict", "detail": "already decided"}
        )
    )
    with pytest.raises(StewardRejected) as caught:
        await steward.decide(cid, True, user_id="u1", scope="team")
    assert caught.value.status == 409


async def test_fake_governance_follows_steward_defaults() -> None:
    fake = FakeSteward()
    assert await fake.report_episode([("user", "你好")], user_id="u1", session_id="s") == []
    [card] = await fake.report_episode(
        [("user", "记住：报销 30 天内提交")], user_id="u1", session_id="s"
    )
    assert (card.stage, card.requested_for_user) == ("awaiting_user", "u1")
    high = await fake.suggest("新价格\n99 元", user_id="u1", session_id="s")
    assert high.candidate is not None and high.candidate.stage == "awaiting_review"
    assert [c.id for c in await fake.list_candidates(stage="awaiting_user", user_id="u1")] == [
        card.id
    ]
    team = await fake.decide(card.id, True, user_id="u1", scope="team")
    assert team.entry is not None and team.entry.status == "active"
    with pytest.raises(StewardRejected):
        await fake.decide(card.id, True, user_id="u1", scope="team")
    assert await fake.list_candidates(stage="awaiting_user", user_id="u1") == []


@respx.mock
async def test_list_candidates_follows_every_page(steward: HttpSteward) -> None:
    first, second = candidate_json(), candidate_json()
    cursor = str(uuid.uuid4())

    def page(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("cursor") == cursor:
            return httpx.Response(200, json={"items": [second], "next_cursor": None})
        return httpx.Response(200, json={"items": [first], "next_cursor": cursor})

    route = respx.get(f"{BASE}/v1/candidates").mock(side_effect=page)
    found = await steward.list_candidates(stage="awaiting_review")
    assert [c.id for c in found] == [first["id"], second["id"]]
    assert route.call_count == 2


@respx.mock
async def test_extraction_gets_more_time_than_a_search() -> None:
    """Episodes and suggestions are model calls on steward's side: a short timeout would drop
    the cards silently."""
    import asyncio

    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.3)
        return httpx.Response(
            200,
            json={
                "episode_id": str(uuid.uuid4()),
                "status": "processed",
                "job_id": None,
                "memories": [],
                "suggestions": [],
            },
        )

    route = respx.post(f"{BASE}/v1/episodes").mock(side_effect=slow)
    steward = HttpSteward(BASE, "stw_k", timeout_s=0.1, model_timeout_s=2.0)
    assert await steward.report_episode([("user", "q")], user_id="u1", session_id="s1") == []
    # respx does not enforce timeouts: check the one the request was sent with
    assert route.calls[0].request.extensions["timeout"]["read"] == 2.0


@respx.mock
async def test_writing_an_entry_gets_the_model_timeout() -> None:
    """Steward judges risk and embeds before it answers a new entry: on a cold model that takes
    longer than a search, and the short timeout failed the first deployment's demo seed."""
    import asyncio

    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.3)
        return httpx.Response(201, json={"entry": entry_json(), "candidate": None})

    respx.get(f"{BASE}/v1/kb/collections").mock(
        return_value=httpx.Response(200, json=collections("company"))
    )
    route = respx.post(f"{BASE}/v1/kb/entries").mock(side_effect=slow)
    steward = HttpSteward(BASE, "stw_k", collection="company", timeout_s=0.1, model_timeout_s=2.0)
    written = await steward.create_entry("差旅制度", "800 元", author="alice")
    assert written.entry is not None and written.entry.status == "active"
    # respx does not enforce timeouts: check the one the request was sent with
    assert route.calls[0].request.extensions["timeout"]["read"] == 2.0
