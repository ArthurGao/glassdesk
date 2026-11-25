import io

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from glassdesk import cli
from glassdesk.app import create_app
from glassdesk.config import Settings
from glassdesk.db import Deps
from glassdesk.users import create_user


@pytest.fixture
def app(settings: Settings, deps: Deps) -> FastAPI:
    return create_app(settings, deps=deps)


@pytest.fixture
async def client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_login_sets_cookie_and_me_returns_user(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    await create_user(engine, "alice", "correct horse", "member")
    response = await client.post(
        "/api/auth/login", json={"username": "alice", "password": "correct horse"}
    )
    assert response.status_code == 200
    assert response.json() == {"username": "alice", "role": "member"}
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    me = await client.get("/api/me")
    assert me.status_code == 200
    assert me.json() == {"username": "alice", "role": "member"}


async def test_wrong_password_and_unknown_user_give_identical_401(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    await create_user(engine, "alice", "correct horse", "member")
    wrong = await client.post("/api/auth/login", json={"username": "alice", "password": "nope"})
    unknown = await client.post("/api/auth/login", json={"username": "bob", "password": "nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert "set-cookie" not in wrong.headers


async def test_me_without_cookie_is_401(client: AsyncClient) -> None:
    assert (await client.get("/api/me")).status_code == 401


async def test_tampered_cookie_is_401(client: AsyncClient, engine: AsyncEngine) -> None:
    await create_user(engine, "alice", "correct horse", "member")
    await client.post("/api/auth/login", json={"username": "alice", "password": "correct horse"})
    value = client.cookies["glassdesk_session"]
    client.cookies.set("glassdesk_session", value[:-2] + ("aa" if value[-2:] != "aa" else "bb"))
    assert (await client.get("/api/me")).status_code == 401


async def test_logout_ends_the_session(client: AsyncClient, engine: AsyncEngine) -> None:
    await create_user(engine, "alice", "correct horse", "member")
    await client.post("/api/auth/login", json={"username": "alice", "password": "correct horse"})
    assert (await client.post("/api/auth/logout")).status_code == 204
    assert (await client.get("/api/me")).status_code == 401


async def test_cli_user_create_rejects_duplicate_username(
    deps: Deps, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    argv = ["user", "create", "alice", "--role", "reviewer", "--password-stdin"]
    monkeypatch.setattr("sys.stdin", io.StringIO("pw-one\n"))
    assert await cli.run(argv, deps=deps) == 0
    monkeypatch.setattr("sys.stdin", io.StringIO("pw-two\n"))
    assert await cli.run(argv, deps=deps) != 0
    async with engine.connect() as conn:
        rows = (await conn.execute(text("select role from users where username='alice'"))).all()
    assert [r.role for r in rows] == ["reviewer"]


async def test_a_cookie_copied_before_logout_is_rejected_after_it(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    await create_user(engine, "alice", "correct horse", "member")
    await client.post("/api/auth/login", json={"username": "alice", "password": "correct horse"})
    stolen = client.cookies["glassdesk_session"]
    assert (await client.post("/api/auth/logout")).status_code == 204
    client.cookies.set("glassdesk_session", stolen)
    assert (await client.get("/api/me")).status_code == 401
