"""Confirmation cards: what steward asks an end user before knowledge goes in (design §5).

steward trusts the key holder with any user id, so the check that a card belongs to the person
deciding it is glassdesk's: an id that is not one of the user's open cards is 404."""

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from glassdesk.auth import CurrentUser
from glassdesk.steward import Candidate, StewardPort
from glassdesk.web import DecisionOut, Steward

router = APIRouter(prefix="/api/suggestions")


class CardOut(BaseModel):
    id: str
    title: str
    content: str
    risk_level: str
    reason: str | None


class AcceptIn(BaseModel):
    scope: Literal["personal", "team"] = "team"


def _card(c: Candidate) -> CardOut:
    return CardOut.model_validate(c, from_attributes=True)


async def open_cards(steward: StewardPort, user_id: str) -> list[CardOut]:
    cards = await steward.list_candidates(stage="awaiting_user", user_id=user_id)
    # steward filtered by user already; this keeps the ownership check ours
    return [_card(c) for c in cards if c.requested_for_user == user_id]


@router.get("")
async def list_cards(steward: Steward, user: CurrentUser) -> list[CardOut]:
    return await open_cards(steward, str(user.id))


async def _decide(
    steward: StewardPort,
    user_id: str,
    card_id: str,
    accept: bool,
    scope: Literal["personal", "team"] | None,
) -> DecisionOut:
    if card_id not in {c.id for c in await open_cards(steward, user_id)}:
        raise HTTPException(404, "no such card")
    return DecisionOut.of(await steward.decide(card_id, accept, user_id=user_id, scope=scope))


@router.post("/{card_id}/accept")
async def accept_card(
    card_id: str, body: AcceptIn, steward: Steward, user: CurrentUser
) -> DecisionOut:
    return await _decide(steward, str(user.id), card_id, True, body.scope)


@router.post("/{card_id}/reject")
async def reject_card(card_id: str, steward: Steward, user: CurrentUser) -> DecisionOut:
    return await _decide(steward, str(user.id), card_id, False, None)
