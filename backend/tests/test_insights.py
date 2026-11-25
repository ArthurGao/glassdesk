import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from glassdesk.testing import FakeSteward
from glassdesk.users import create_user
from tests.helpers import client_for, search_then_answer

NOW = datetime(2026, 11, 25, 4, 0, tzinfo=UTC)  # 12:00 in Shanghai, 2026-11-25


async def add_run(
    engine: AsyncEngine,
    finished_at: datetime,
    *,
    cost: str | None,
    failed: bool = False,
    tokens: tuple[int | None, int | None] = (100, 20),
    helpful: bool | None = None,
) -> None:
    async with engine.begin() as conn:
        user_id = (await conn.execute(text("select id from users limit 1"))).scalar_one()
        run_id = uuid.uuid4().hex
        await conn.execute(
            text("insert into run_usage values (:r, :c, :u, :t, :i, :o, :cost, :f)"),
            {
                "r": run_id,
                "c": uuid.uuid4(),
                "u": user_id,
                "t": finished_at,
                "i": tokens[0],
                "o": tokens[1],
                "cost": Decimal(cost) if cost else None,
                "f": failed,
            },
        )
        if helpful is not None:
            await conn.execute(
                text("insert into answer_feedback (run_id, user_id, helpful) values (:r, :u, :h)"),
                {"r": run_id, "u": user_id, "h": helpful},
            )


async def reviewer_client(
    make_app: Callable[..., FastAPI], engine: AsyncEngine, steward: FakeSteward
):  # type: ignore[no-untyped-def]
    app = make_app(search_then_answer("a"), steward)
    app.state.clock = lambda: NOW
    return await client_for(app, engine, "rita", role="reviewer")


async def test_unknown_cost_is_counted_apart_and_an_empty_day_has_no_cost(
    make_app: Callable[..., FastAPI], engine: AsyncEngine
) -> None:
    client = await reviewer_client(make_app, engine, FakeSteward())
    day = datetime(2026, 11, 24, 2, 0, tzinfo=UTC)  # 2026-11-24 in Shanghai
    await add_run(engine, day, cost="0.010")
    await add_run(engine, day, cost="0.020", failed=True)
    await add_run(engine, day, cost=None, tokens=(None, None))
    body = (await client.get("/api/insights")).json()
    days = {d["day"]: d for d in body["days"]}
    assert [d["day"] for d in body["days"]] == [f"2026-11-{n}" for n in range(19, 26)]
    assert days["2026-11-24"] == {
        "day": "2026-11-24",
        "answers": 3,
        "failed": 1,
        "tokens": 240,
        "cost_usd": 0.03,
        "cost_unknown_runs": 1,
    }
    assert days["2026-11-23"] == {
        "day": "2026-11-23",
        "answers": 0,
        "failed": 0,
        "tokens": 0,
        "cost_usd": None,
        "cost_unknown_runs": 0,
    }
    assert body["totals"]["cost_usd"] == 0.03 and body["totals"]["cost_unknown_runs"] == 1


async def test_a_run_just_after_local_midnight_counts_on_the_local_day(
    make_app: Callable[..., FastAPI], engine: AsyncEngine
) -> None:
    client = await reviewer_client(make_app, engine, FakeSteward())
    await add_run(engine, datetime(2026, 11, 24, 16, 30, tzinfo=UTC), cost="0.01")  # 00:30 +08
    days = {d["day"]: d["answers"] for d in (await client.get("/api/insights")).json()["days"]}
    assert (days["2026-11-24"], days["2026-11-25"]) == (0, 1)


async def test_helpful_rate_leaves_unrated_answers_out(
    make_app: Callable[..., FastAPI], engine: AsyncEngine
) -> None:
    client = await reviewer_client(make_app, engine, FakeSteward())
    assert (await client.get("/api/insights")).json()["helpful_rate"] is None
    await add_run(engine, NOW, cost=None, helpful=True)
    await add_run(engine, NOW, cost=None, helpful=False)
    await add_run(engine, NOW, cost=None)
    body = (await client.get("/api/insights")).json()
    assert (body["helpful_rate"], body["rated"]) == (0.5, 2)


async def test_kb_numbers_come_from_steward_and_are_labelled_demo_in_fake_mode(
    make_app: Callable[..., FastAPI], engine: AsyncEngine
) -> None:
    client = await reviewer_client(make_app, engine, FakeSteward())
    body = (await client.get("/api/insights")).json()
    assert body["demo"] is True
    assert body["kb"]["gaps"][0] == {"query": "海外差旅住宿标准", "count": 3}


async def test_steward_stats_down_still_answers_without_the_kb_part(
    make_app: Callable[..., FastAPI], engine: AsyncEngine
) -> None:
    client = await reviewer_client(make_app, engine, FakeSteward(fail=True))
    body = (await client.get("/api/insights")).json()
    assert (body["kb"], body["totals"]["answers"]) == (None, 0)


async def test_members_cannot_see_insights(
    make_app: Callable[..., FastAPI], engine: AsyncEngine
) -> None:
    client = await client_for(make_app(search_then_answer("a"), FakeSteward()), engine, "alice")
    assert (await client.get("/api/insights")).status_code == 403
    await create_user(engine, "x", "pw", "member")
