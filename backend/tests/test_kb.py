import uuid
from collections.abc import Callable

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from glassdesk.steward import Entry
from glassdesk.testing import FakeSteward
from tests.helpers import client_for, search_then_answer


async def test_a_manual_entry_goes_live_or_waits_for_review(
    make_app: Callable[..., FastAPI], engine: AsyncEngine
) -> None:
    steward = FakeSteward()
    client = await client_for(make_app(search_then_answer("a"), steward), engine, "alice")
    live = await client.post("/api/kb/entries", json={"title": "报销时限", "content": "30 天内"})
    assert live.status_code == 201
    assert live.json()["entry"]["status"] == "active" and live.json()["candidate"] is None
    review = await client.post("/api/kb/entries", json={"title": "价格表", "content": "99 元"})
    assert review.json()["entry"] is None
    assert review.json()["candidate"]["stage"] == "awaiting_review"
    listed = (await client.get("/api/kb/entries")).json()
    assert [e["title"] for e in listed] == ["报销时限"]


async def test_upload_checks_size_and_type_before_steward(
    make_app: Callable[..., FastAPI], engine: AsyncEngine
) -> None:
    steward = FakeSteward()
    client = await client_for(make_app(search_then_answer("a"), steward), engine, "alice")
    ok = await client.post(
        "/api/kb/documents",
        files={"file": ("guide.md", b"# hi", "text/markdown")},
        data={"title": "指南"},
    )
    assert ok.status_code == 201
    assert ok.json()["document"]["title"] == "指南"
    empty = await client.post("/api/kb/documents", files={"file": ("e.md", b"", "text/markdown")})
    big = await client.post(
        "/api/kb/documents", files={"file": ("b.txt", b"x" * (20 * 1024 * 1024 + 1), "text/plain")}
    )
    exe = await client.post("/api/kb/documents", files={"file": ("a.exe", b"MZ", "application/x")})
    assert [r.status_code for r in (empty, big, exe)] == [422, 422, 422]
    assert [d.filename for d in steward.documents] == ["guide.md"]
    assert [d["filename"] for d in (await client.get("/api/kb/documents")).json()] == ["guide.md"]


async def test_members_cannot_see_or_decide_reviews(
    make_app: Callable[..., FastAPI], engine: AsyncEngine
) -> None:
    steward = FakeSteward()
    client = await client_for(make_app(search_then_answer("a"), steward), engine, "alice")
    await client.post("/api/kb/entries", json={"title": "价格表", "content": "99 元"})
    [cand] = steward.candidates
    assert (await client.get("/api/kb/reviews")).status_code == 403
    for action in ("approve", "reject"):
        response = await client.post(f"/api/kb/reviews/{cand.id}/{action}", json={})
        assert response.status_code == 403
    assert cand.status == "pending"


async def test_a_reviewer_approves_and_the_audit_names_them(
    make_app: Callable[..., FastAPI], engine: AsyncEngine
) -> None:
    steward = FakeSteward()
    app = make_app(search_then_answer("a"), steward)
    member = await client_for(app, engine, "alice")
    reviewer = await client_for(app, engine, "rita", role="reviewer")
    await member.post("/api/kb/entries", json={"title": "价格表", "content": "99 元"})
    [review] = (await reviewer.get("/api/kb/reviews")).json()
    assert (review["title"], review["risk_level"]) == ("价格表", "high")
    decided = await reviewer.post(
        f"/api/kb/reviews/{review['id']}/approve", json={"note": "已核对"}
    )
    assert decided.json() == {"status": "accepted", "entry_status": "verified"}
    assert (await reviewer.get("/api/kb/reviews")).json() == []
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "select a.candidate_id, a.action, a.note, u.username from review_audit a "
                    "join users u on u.id = a.user_id"
                )
            )
        ).all()
    assert [tuple(r) for r in rows] == [(review["id"], "approve", "已核对", "rita")]


async def test_reviewing_something_not_in_the_queue_is_404(
    make_app: Callable[..., FastAPI], engine: AsyncEngine
) -> None:
    client = await client_for(
        make_app(search_then_answer("a"), FakeSteward()), engine, "rita", role="admin"
    )
    response = await client.post("/api/kb/reviews/not-a-candidate/approve", json={})
    assert response.status_code == 404


async def _live_entry(client: AsyncClient) -> str:
    live = await client.post("/api/kb/entries", json={"title": "报销时限", "content": "30 天内"})
    entry_id: str = live.json()["entry"]["id"]
    return entry_id


async def test_members_cannot_deprecate_an_entry(
    make_app: Callable[..., FastAPI], engine: AsyncEngine
) -> None:
    steward = FakeSteward()
    client = await client_for(make_app(search_then_answer("a"), steward), engine, "alice")
    entry_id = await _live_entry(client)
    response = await client.post(f"/api/kb/entries/{entry_id}/deprecate", json={})
    assert response.status_code == 403
    assert [e.status for e in steward.entries] == ["active"]


async def test_a_reviewer_deprecates_an_entry_and_the_audit_names_them(
    make_app: Callable[..., FastAPI], engine: AsyncEngine
) -> None:
    steward = FakeSteward()
    app = make_app(search_then_answer("a"), steward)
    member = await client_for(app, engine, "alice")
    reviewer = await client_for(app, engine, "rita", role="reviewer")
    admin = await client_for(app, engine, "adam", role="admin")
    first = await _live_entry(member)
    second = await _live_entry(member)
    done = await reviewer.post(
        f"/api/kb/entries/{first}/deprecate", json={"reason": "已被新制度取代"}
    )
    assert done.status_code == 200
    assert (done.json()["id"], done.json()["status"]) == (first, "deprecated")
    assert (await admin.post(f"/api/kb/entries/{second}/deprecate", json={})).status_code == 200
    listed = {e["id"]: e["status"] for e in (await member.get("/api/kb/entries")).json()}
    assert listed == {first: "deprecated", second: "deprecated"}
    again = await reviewer.post(f"/api/kb/entries/{first}/deprecate", json={})
    assert again.status_code == 409
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "select a.entry_id, a.candidate_id, a.action, a.note, u.username "
                    "from review_audit a join users u on u.id = a.user_id order by a.created_at"
                )
            )
        ).all()
    assert [tuple(r) for r in rows] == [
        (first, None, "deprecate", "已被新制度取代", "rita"),
        (second, None, "deprecate", None, "adam"),
    ]


async def test_deprecating_an_unknown_entry_is_404_and_writes_no_audit(
    make_app: Callable[..., FastAPI], engine: AsyncEngine
) -> None:
    client = await client_for(
        make_app(search_then_answer("a"), FakeSteward()), engine, "rita", role="reviewer"
    )
    response = await client.post(f"/api/kb/entries/{uuid.uuid4()}/deprecate", json={})
    assert response.status_code == 404
    async with engine.connect() as conn:
        assert (await conn.scalar(text("select count(*) from review_audit"))) == 0


async def test_a_malformed_entry_id_is_422_before_steward_is_asked(
    make_app: Callable[..., FastAPI], engine: AsyncEngine
) -> None:
    class Counting(FakeSteward):
        asked = 0

        async def deprecate(self, entry_id: str) -> Entry:
            self.asked += 1
            return await super().deprecate(entry_id)

    steward = Counting()
    client = await client_for(make_app(search_then_answer("a"), steward), engine, "rita", "admin")
    response = await client.post("/api/kb/entries/not-a-uuid/deprecate", json={})
    assert (response.status_code, steward.asked) == (422, 0)
