"""What the knowledge routes share: the steward dependency, how steward's refusals become HTTP
answers, and the shape of a decision."""

from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from glassdesk.db import Deps
from glassdesk.i18n import texts_for
from glassdesk.steward import Decision, StewardPort, StewardRejected, StewardUnavailable


def _steward(request: Request) -> StewardPort:
    deps: Deps = request.app.state.deps
    if deps.steward is None:
        raise HTTPException(503, texts_for(request).kb_not_configured)
    return deps.steward


Steward = Annotated[StewardPort, Depends(_steward)]


class DecisionOut(BaseModel):
    status: str
    entry_status: str | None  # the entry an accepted decision made, when there is one

    @classmethod
    def of(cls, decision: Decision) -> "DecisionOut":
        entry = decision.entry
        return cls(status=decision.candidate.status, entry_status=entry.status if entry else None)


def register_steward_errors(app: FastAPI) -> None:
    """steward's refusals keep their status and short detail (409: someone already decided);
    steward being unreachable is 503 without its text."""

    @app.exception_handler(StewardRejected)
    async def rejected(request: Request, exc: StewardRejected) -> JSONResponse:
        detail = texts_for(request).already_decided if exc.status == 409 else exc.message
        return JSONResponse({"detail": detail}, status_code=exc.status)

    @app.exception_handler(StewardUnavailable)
    async def unavailable(request: Request, exc: StewardUnavailable) -> JSONResponse:
        return JSONResponse({"detail": texts_for(request).kb_unavailable}, status_code=503)
