import json
import uuid

import httpx
import pytest
import respx

from glassdesk.steward import HttpSteward, StewardRejected, StewardUnavailable
from glassdesk.testing import FakeSteward

BASE = "http://steward.test"
COL = str(uuid.uuid4())
NOW = "2026-11-25T09:00:00Z"


def entry_json(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": str(uuid.uuid4()),
        "collection_id": COL,
        "title": "差旅制度",
        "content": "800 元",
        "status": "active",
        "risk_level": "low",
        "origin": "manual",
        "author_type": "human",
        "hit_count": 3,
        "helpful_count": None,
        "unhelpful_count": None,
        "tags": [],
        "source_refs": [],
        "version": 1,
        "created_at": NOW,
        "updated_at": NOW,
        "valid_from": NOW,
        "created_by": None,
        "review_due_at": None,
        "superseded_by": None,
        "valid_to": None,
        "verified_at": None,
        "verified_by": None,
    }
    return base | over


def candidate_json(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": str(uuid.uuid4()),
        "op": "ADD",
        "origin": "api",
        "risk_level": "high",
        "stage": "awaiting_review",
        "status": "pending",
        "target_type": "kb_entry",
        "target_id": None,
        "draft": {"title": "价格表", "content": "A 套餐 99 元"},
        "reason": "命中关键词：价格",
        "requested_for_user": None,
        "created_at": NOW,
        "decided_at": None,
        "decided_by": None,
        "decision_note": None,
        "expires_at": None,
    }
    return base | over


def document_json(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": str(uuid.uuid4()),
        "collection_id": COL,
        "title": "入职指南",
        "filename": "onboarding.md",
        "content_hash": "h",
        "mime": "text/markdown",
        "risk_level": "low",
        "size_bytes": 12,
        "state": "active",
        "status": "processing",
        "error": None,
        "created_at": NOW,
        "updated_at": NOW,
        "created_by": None,
        "valid_to": None,
    }
    return base | over


def collections(*names: str) -> dict[str, object]:
    return {
        "items": [
            {"id": COL, "name": n, "default_risk": "low", "review_policy": {}, "created_at": NOW}
            for n in names
        ]
    }


@pytest.fixture
def steward() -> HttpSteward:
    return HttpSteward(BASE, "stw_k", "stw_r", collection="company", timeout_s=0.2)


@respx.mock
async def test_ensure_collection_creates_it_once_and_caches(steward: HttpSteward) -> None:
    listed = respx.get(f"{BASE}/v1/kb/collections").mock(
        return_value=httpx.Response(200, json=collections("other"))
    )
    created = respx.post(f"{BASE}/v1/kb/collections").mock(
        return_value=httpx.Response(201, json=collections("company")["items"][0])  # type: ignore[index]
    )
    assert await steward.ensure_collection() == COL
    assert await steward.ensure_collection() == COL
    assert (listed.call_count, created.call_count) == (1, 1)
    assert json.loads(created.calls[0].request.content)["name"] == "company"
    # creating a collection sets its review policy: steward allows it to a reviewer only
    assert listed.calls[0].request.headers["authorization"] == "Bearer stw_k"
    assert created.calls[0].request.headers["authorization"] == "Bearer stw_r"


@respx.mock
async def test_create_entry_sends_collection_and_author_and_maps_entry(
    steward: HttpSteward,
) -> None:
    respx.get(f"{BASE}/v1/kb/collections").mock(
        return_value=httpx.Response(200, json=collections("company"))
    )
    e = entry_json()
    route = respx.post(f"{BASE}/v1/kb/entries").mock(
        return_value=httpx.Response(201, json={"entry": e, "candidate": None})
    )
    written = await steward.create_entry("差旅制度", "800 元", author="alice")
    assert written.candidate is None and written.entry is not None
    assert (written.entry.id, written.entry.status, written.entry.hit_count) == (
        e["id"],
        "active",
        3,
    )
    body = json.loads(route.calls[0].request.content)
    assert body["collection_id"] == COL
    assert body["source_refs"] == [{"type": "glassdesk_user", "id": "alice"}]


@respx.mock
async def test_create_entry_that_needs_review_comes_back_as_a_candidate(
    steward: HttpSteward,
) -> None:
    respx.get(f"{BASE}/v1/kb/collections").mock(
        return_value=httpx.Response(200, json=collections("company"))
    )
    c = candidate_json()
    respx.post(f"{BASE}/v1/kb/entries").mock(
        return_value=httpx.Response(201, json={"entry": None, "candidate": c})
    )
    written = await steward.create_entry("价格表", "A 套餐 99 元", author="alice")
    assert written.entry is None and written.candidate is not None
    cand = written.candidate
    assert (cand.stage, cand.title, cand.content, cand.reason) == (
        "awaiting_review",
        "价格表",
        "A 套餐 99 元",
        "命中关键词：价格",
    )


@respx.mock
async def test_upload_document_posts_multipart_with_collection(steward: HttpSteward) -> None:
    respx.get(f"{BASE}/v1/kb/collections").mock(
        return_value=httpx.Response(200, json=collections("company"))
    )
    d = document_json()
    route = respx.post(f"{BASE}/v1/kb/documents").mock(
        return_value=httpx.Response(202, json={"document": d, "candidate": None})
    )
    doc, cand = await steward.upload_document(
        "onboarding.md", b"# hello", "text/markdown", title="入职指南"
    )
    assert (doc.id, doc.status, doc.size_bytes, cand) == (d["id"], "processing", 12, None)
    sent = route.calls[0].request.content
    assert b'name="collection_id"' in sent and COL.encode() in sent
    assert b'filename="onboarding.md"' in sent and b"# hello" in sent


@respx.mock
async def test_list_entries_and_documents_filter_by_collection(steward: HttpSteward) -> None:
    respx.get(f"{BASE}/v1/kb/collections").mock(
        return_value=httpx.Response(200, json=collections("company"))
    )
    entries = respx.get(f"{BASE}/v1/kb/entries").mock(
        return_value=httpx.Response(200, json={"items": [entry_json()], "next_cursor": None})
    )
    docs = respx.get(f"{BASE}/v1/kb/documents").mock(
        return_value=httpx.Response(200, json={"items": [document_json()], "next_cursor": None})
    )
    assert len(await steward.list_entries()) == 1
    assert len(await steward.list_documents()) == 1
    assert entries.calls[0].request.url.params["collection_id"] == COL
    assert docs.calls[0].request.url.params["collection_id"] == COL


@respx.mock
async def test_a_4xx_is_rejected_with_stewards_short_detail(steward: HttpSteward) -> None:
    respx.get(f"{BASE}/v1/kb/collections").mock(
        return_value=httpx.Response(200, json=collections("company"))
    )
    respx.post(f"{BASE}/v1/kb/entries").mock(
        return_value=httpx.Response(
            422,
            json={
                "type": "about:blank",
                "status": 422,
                "code": "invalid",
                "detail": "title too long",
            },
        )
    )
    with pytest.raises(StewardRejected) as caught:
        await steward.create_entry("x", "y", author="alice")
    assert (caught.value.status, caught.value.message) == (422, "title too long")


@respx.mock
async def test_a_5xx_while_listing_is_unavailable(steward: HttpSteward) -> None:
    respx.get(f"{BASE}/v1/kb/collections").mock(return_value=httpx.Response(503, json={}))
    with pytest.raises(StewardUnavailable):
        await steward.list_entries()


async def test_fake_puts_low_risk_entries_live_and_sends_high_risk_to_review() -> None:
    fake = FakeSteward()
    live = await fake.create_entry("报销时限", "30 天内提交", author="alice")
    review = await fake.create_entry("价格表", "A 套餐 99 元", author="alice")
    assert live.entry is not None and live.entry.status == "active"
    assert review.candidate is not None and review.candidate.stage == "awaiting_review"
    assert [e.title for e in await fake.list_entries()] == ["报销时限"]


@respx.mock
async def test_deprecate_checks_the_entry_is_ours_then_uses_the_review_key(
    steward: HttpSteward,
) -> None:
    respx.get(f"{BASE}/v1/kb/collections").mock(
        return_value=httpx.Response(200, json=collections("company"))
    )
    eid = str(uuid.uuid4())
    got = respx.get(f"{BASE}/v1/kb/entries/{eid}").mock(
        return_value=httpx.Response(200, json=entry_json(id=eid))
    )
    route = respx.post(f"{BASE}/v1/kb/entries/{eid}/deprecate").mock(
        return_value=httpx.Response(200, json=entry_json(id=eid, status="deprecated"))
    )
    entry = await steward.deprecate(eid)
    assert (entry.id, entry.status) == (eid, "deprecated")
    # deprecating is a reviewer's act in steward; reading the entry is not
    assert got.calls[0].request.headers["authorization"] == "Bearer stw_k"
    assert route.calls[0].request.headers["authorization"] == "Bearer stw_r"


@respx.mock
async def test_deprecate_refuses_an_entry_of_another_collection(steward: HttpSteward) -> None:
    respx.get(f"{BASE}/v1/kb/collections").mock(
        return_value=httpx.Response(200, json=collections("company"))
    )
    eid = str(uuid.uuid4())
    respx.get(f"{BASE}/v1/kb/entries/{eid}").mock(
        return_value=httpx.Response(200, json=entry_json(id=eid, collection_id=str(uuid.uuid4())))
    )
    route = respx.post(f"{BASE}/v1/kb/entries/{eid}/deprecate")
    with pytest.raises(StewardRejected) as caught:
        await steward.deprecate(eid)
    assert caught.value.status == 404
    assert route.call_count == 0


async def test_fake_deprecates_an_entry_once_and_lists_it_as_deprecated() -> None:
    fake = FakeSteward()
    written = await fake.create_entry("报销时限", "30 天内提交", author="alice")
    assert written.entry is not None
    deprecated = await fake.deprecate(written.entry.id)
    assert deprecated.status == "deprecated"
    assert [(e.title, e.status) for e in await fake.list_entries()] == [("报销时限", "deprecated")]
    with pytest.raises(StewardRejected) as twice:
        await fake.deprecate(written.entry.id)
    with pytest.raises(StewardRejected) as unknown:
        await fake.deprecate("no-such-entry")
    assert (twice.value.status, unknown.value.status) == (409, 404)


@pytest.mark.parametrize(
    ("response", "unsent"),
    [
        (httpx.ConnectError("refused"), True),  # never reached steward
        (httpx.ConnectTimeout("slow"), True),
        (httpx.ReadTimeout("slow"), False),  # sent: steward may have acted
        (httpx.Response(503, json={}), False),
        (httpx.Response(403, json={}), True),  # refused before doing anything
    ],
)
@respx.mock
async def test_unavailable_says_whether_steward_certainly_did_nothing(
    steward: HttpSteward, response: object, unsent: bool
) -> None:
    respx.get(f"{BASE}/v1/kb/collections").mock(
        return_value=httpx.Response(200, json=collections("company"))
    )
    route = respx.post(f"{BASE}/v1/suggestions")
    if isinstance(response, httpx.Response):
        route.mock(return_value=response)
    else:
        route.mock(side_effect=response)
    with pytest.raises(StewardUnavailable) as caught:
        await steward.suggest("t\nc", user_id="u1", session_id="s1")
    assert caught.value.unsent is unsent
