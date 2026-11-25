import json
import uuid

import httpx
import pytest
import respx

from glassdesk.steward import HttpSteward, StewardUnavailable

BASE = "http://steward.test"
RID = str(uuid.uuid4())


def item(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": str(uuid.uuid4()),
        "kind": "entry",
        "content": "full content",
        "passages": None,
        "pinned": False,
        "score": 0.8,
        "source": "kb",
        "status": "verified",
        "title": "差旅制度 v3",
        "verified": True,
    }
    return base | over


@pytest.fixture
async def steward() -> HttpSteward:
    return HttpSteward(BASE, "stw_k", "stw_r", timeout_s=0.2)


@respx.mock
async def test_search_maps_items_to_passages(steward: HttpSteward) -> None:
    a = item(passages=["p1", "p2"])
    b = item(kind="memory", source="memory", title=None, verified=False, content="m1", score=0.5)
    route = respx.post(f"{BASE}/v1/retrieve").mock(
        return_value=httpx.Response(
            200, json={"retrieval_id": RID, "items": [a, b], "degraded": []}
        )
    )
    result = await steward.search("报销上限", user_id="u1", session_id="s1")
    assert result.retrieval_id == RID
    assert [(p.kind, p.title, p.text, p.verified, p.score) for p in result.passages] == [
        ("entry", "差旅制度 v3", "p1", True, 0.8),
        ("memory", None, "m1", False, 0.5),
    ]
    assert result.passages[0].item_id == a["id"]
    body = json.loads(route.calls[0].request.content)
    assert body["query"] == "报销上限"
    assert body["scope"] == {"user_id": "u1", "session_id": "s1"}
    assert route.calls[0].request.headers["authorization"] == "Bearer stw_k"


@respx.mock
async def test_search_timeout_raises_steward_unavailable(steward: HttpSteward) -> None:
    respx.post(f"{BASE}/v1/retrieve").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(StewardUnavailable):
        await steward.search("q", user_id="u1", session_id="s1")


@respx.mock
async def test_search_5xx_raises_without_upstream_text(steward: HttpSteward) -> None:
    respx.post(f"{BASE}/v1/retrieve").mock(
        return_value=httpx.Response(500, json={"detail": "secret-token-xyz"})
    )
    with pytest.raises(StewardUnavailable) as caught:
        await steward.search("q", user_id="u1", session_id="s1")
    assert "secret-token-xyz" not in str(caught.value)


@respx.mock
async def test_degraded_is_passed_through(steward: HttpSteward) -> None:
    respx.post(f"{BASE}/v1/retrieve").mock(
        return_value=httpx.Response(
            200, json={"retrieval_id": RID, "items": [], "degraded": ["kb"]}
        )
    )
    result = await steward.search("q", user_id="u1", session_id="s1")
    assert result.degraded == ("kb",)
    assert result.passages == ()
