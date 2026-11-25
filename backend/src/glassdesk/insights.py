"""Insights for reviewers and admins (design §4): answers, failures, tokens and cost per local
day, the helpful rate, and steward's view of the KB.

Unknown is not zero (KB dates-time-and-metrics §4): a run whose endpoint reported no cost is
left out of the cost sum and counted apart; unrated answers leave the helpful-rate denominator."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import Date, case, cast, func, select

from glassdesk.auth import Reviewer
from glassdesk.conversations import answer_feedback, run_usage
from glassdesk.db import Deps

DAYS = 7

router = APIRouter(prefix="/api/insights")


class DayOut(BaseModel):
    day: date
    answers: int
    failed: int
    tokens: int  # known tokens; a run that reported none adds nothing
    cost_usd: float | None  # sum of known costs; None when no run reported one
    cost_unknown_runs: int


class Gap(BaseModel):
    query: str
    count: int


class KbOut(BaseModel):
    entries_by_status: dict[str, int]
    pending_reviews: int
    awaiting_user: int
    gaps: list[Gap]


class InsightsOut(BaseModel):
    days: list[DayOut]  # oldest first, every day of the window, empty ones included
    totals: DayOut
    helpful_rate: float | None  # None: nothing rated in the window
    rated: int
    kb: KbOut | None  # None: steward's Admin API not configured or not answering
    demo: bool  # the KB numbers are made up (fake mode)


def _day(
    day: date, answers: int, failed: int, tokens: int, known: int, cost: float | None
) -> DayOut:
    return DayOut(
        day=day,
        answers=answers,
        failed=failed,
        tokens=tokens,
        cost_usd=cost if known else None,
        cost_unknown_runs=answers - known,
    )


@router.get("")
async def insights(request: Request, user: Reviewer) -> InsightsOut:
    deps: Deps = request.app.state.deps
    tz = ZoneInfo(request.app.state.settings.timezone)
    today = request.app.state.clock().astimezone(tz).date()
    first = today - timedelta(days=DAYS - 1)
    since = datetime.combine(first, time.min, tzinfo=tz)
    local_day = cast(func.timezone(tz.key, run_usage.c.finished_at), Date)
    known = run_usage.c.cost_usd.is_not(None)
    async with deps.engine.connect() as conn:
        rows = (
            await conn.execute(
                select(
                    local_day.label("day"),
                    func.count().label("answers"),
                    func.count().filter(run_usage.c.failed).label("failed"),
                    func.coalesce(
                        func.sum(
                            func.coalesce(run_usage.c.input_tokens, 0)
                            + func.coalesce(run_usage.c.output_tokens, 0)
                        ),
                        0,
                    ).label("tokens"),
                    func.count().filter(known).label("known"),
                    func.sum(run_usage.c.cost_usd).label("cost"),
                )
                .where(run_usage.c.finished_at >= since)
                .group_by(local_day)
            )
        ).all()
        rated_row = (
            await conn.execute(
                select(
                    func.count().label("rated"),
                    func.coalesce(func.sum(case((answer_feedback.c.helpful, 1), else_=0)), 0).label(
                        "helpful"
                    ),
                )
                .select_from(
                    answer_feedback.join(run_usage, run_usage.c.run_id == answer_feedback.c.run_id)
                )
                .where(run_usage.c.finished_at >= since)
            )
        ).one()
    by_day = {r.day: r for r in rows}
    days = []
    for i in range(DAYS):
        d = first + timedelta(days=i)
        r = by_day.get(d)
        cost = float(r.cost) if r is not None and r.cost is not None else None
        days.append(
            _day(d, r.answers, r.failed, int(r.tokens), r.known, cost)
            if r is not None
            else _day(d, 0, 0, 0, 0, None)
        )
    known_total = sum(d.answers - d.cost_unknown_runs for d in days)
    totals = _day(
        today,
        sum(d.answers for d in days),
        sum(d.failed for d in days),
        sum(d.tokens for d in days),
        known_total,
        round(sum(d.cost_usd or 0.0 for d in days), 6) if known_total else None,
    )
    stats = await deps.steward.stats() if deps.steward is not None else None
    kb = (
        KbOut(
            entries_by_status=stats.entries_by_status,
            pending_reviews=stats.pending_reviews,
            awaiting_user=stats.awaiting_user,
            gaps=[Gap(query=q, count=c) for q, c in stats.gaps],
        )
        if stats is not None
        else None
    )
    rated = int(rated_row.rated)
    return InsightsOut(
        days=days,
        totals=totals,
        helpful_rate=int(rated_row.helpful) / rated if rated else None,
        rated=rated,
        kb=kb,
        demo=bool(stats and stats.demo),
    )
