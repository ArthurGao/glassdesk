"""Login with a signed session cookie (design §7)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel

from glassdesk.users import Role, User, authenticate, get_user

COOKIE = "glassdesk_session"
MAX_AGE_S = 7 * 24 * 3600


class LoginIn(BaseModel):
    username: str
    password: str


class MeOut(BaseModel):
    username: str
    role: Role


def _serializer(request: Request) -> URLSafeTimedSerializer:
    secret = request.app.state.settings.session_secret.get_secret_value()
    return URLSafeTimedSerializer(secret, salt="glassdesk-session")


async def current_user(request: Request) -> User:
    token = request.cookies.get(COOKIE)
    if token is None:
        raise HTTPException(401, "not logged in")
    try:
        user_id = _serializer(request).loads(token, max_age=MAX_AGE_S)
        user = await get_user(request.app.state.deps.engine, uuid.UUID(user_id))
    except (BadSignature, ValueError):
        user = None
    if user is None:
        raise HTTPException(401, "not logged in")
    return user


CurrentUser = Annotated[User, Depends(current_user)]

router = APIRouter(prefix="/api")


@router.post("/auth/login")
async def login(body: LoginIn, request: Request, response: Response) -> MeOut:
    user = await authenticate(request.app.state.deps.engine, body.username, body.password)
    if user is None:
        raise HTTPException(401, "用户名或密码错误")
    response.set_cookie(
        COOKIE,
        _serializer(request).dumps(str(user.id)),
        max_age=MAX_AGE_S,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )
    return MeOut(username=user.username, role=user.role)


@router.post("/auth/logout", status_code=204)
async def logout(response: Response) -> None:
    response.delete_cookie(COOKIE)


@router.get("/me")
async def me(user: CurrentUser) -> MeOut:
    return MeOut(username=user.username, role=user.role)
