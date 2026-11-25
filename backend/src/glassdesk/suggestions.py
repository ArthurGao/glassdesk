"""Confirmation cards: what steward asks an end user before knowledge goes in (design §5).

steward trusts the key holder with any user id, so the check that a card belongs to the person
deciding it is glassdesk's: an id that is not one of the user's open cards is 404."""

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from glassdesk.auth import CurrentUser
from glassdesk.db import Deps
from glassdesk.steward import Candidate, StewardPort, StewardRejected, StewardUnavailable

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/suggestions")


class CardOut(BaseModel):
    id: str
    title: str
    content: str
    risk_level: str
    reason: str | None

    @classmethod
    def of(cls, c: Candidate) -> "CardOut":
        return cls(
            id=c.id, title=c.title, content=c.content, risk_level=c.risk_level, reason=c.reason
        )


class AcceptIn(BaseModel):
    scope: Literal["personal", "team"] = "team"


class DecisionOut(BaseModel):
    status: str
    entry_status: str | None  # the entry an accepted team card made, when there is one


async def open_cards(steward: StewardPort, user_id: str) -> list[CardOut]:
    cards = await steward.list_candidates(stage="awaiting_user", user_id=user_id)
    return [CardOut.of(c) for c in cards if c.requested_for_user == user_id]


def _steward(request: Request) -> StewardPort:
    deps: Deps = request.app.state.deps
    if deps.steward is None:
        raise HTTPException(503, "知识库未配置")
    return deps.steward


@router.get("")
async def list_cards(request: Request, user: CurrentUser) -> list[CardOut]:
    try:
        return await open_cards(_steward(request), str(user.id))
    except StewardUnavailable:
        raise HTTPException(503, "知识库暂时不可用") from None


async def _decide(
    request: Request, user_id: str, card_id: str, accept: bool, scope: str | None
) -> DecisionOut:
    steward = _steward(request)
    try:
        if card_id not in {c.id for c in await open_cards(steward, user_id)}:
            raise HTTPException(404, "no such card")
        decision = await steward.decide(
            card_id,
            accept,
            user_id=user_id,
            scope=scope,  # type: ignore[arg-type]
        )
    except StewardRejected as exc:
        if exc.status == 409:
            raise HTTPException(409, "已处理") from None
        raise HTTPException(exc.status, exc.message) from None
    except StewardUnavailable:
        raise HTTPException(503, "知识库暂时不可用") from None
    return DecisionOut(
        status=decision.candidate.status,
        entry_status=decision.entry.status if decision.entry else None,
    )


@router.post("/{card_id}/accept")
async def accept_card(
    card_id: str, body: AcceptIn, request: Request, user: CurrentUser
) -> DecisionOut:
    return await _decide(request, str(user.id), card_id, True, body.scope)


@router.post("/{card_id}/reject")
async def reject_card(card_id: str, request: Request, user: CurrentUser) -> DecisionOut:
    return await _decide(request, str(user.id), card_id, False, None)
