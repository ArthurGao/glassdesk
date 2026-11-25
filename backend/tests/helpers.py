"""Shared test builders."""

import asyncio
import json
from typing import Any

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from lite_model import AssistantTurn, Text, ToolCall
from lite_model.testing import AsyncFakeModel
from sqlalchemy.ext.asyncio import AsyncEngine

from glassdesk.agent import ROLE
from glassdesk.steward import Passage
from glassdesk.users import Role, create_user

P1 = Passage(
    item_id="e1",
    kind="entry",
    title="差旅制度 v3",
    source="kb",
    text="住宿上限每晚 800 元",
    score=0.9,
    verified=True,
)


def search_then_answer(*answers: str, query: str = "报销上限") -> AsyncFakeModel:
    """One search and one answer per run, for as many runs as answers are given."""
    script: list[AssistantTurn] = []
    for i, answer in enumerate(answers):
        script.append(AssistantTurn((ToolCall(f"c{i + 1}", "search_knowledge", {"query": query}),)))
        script.append(AssistantTurn((Text(answer),)))
    return AsyncFakeModel(**{ROLE: script})


class BlockingModel:
    """Waits for `release` before every turn, so a test can act while a run is going."""

    def __init__(self, inner: AsyncFakeModel) -> None:
        self.inner = inner
        self.release = asyncio.Event()

    async def turn(self, *args: Any, **kwargs: Any) -> Any:
        await self.release.wait()
        return await self.inner.turn(*args, **kwargs)


def parse_sse(body: str) -> list[tuple[str, str | None, Any]]:
    """(event, id, data) per message of a text/event-stream body."""
    out = []
    for block in body.strip().split("\n\n"):
        fields: dict[str, str] = {}
        for line in block.splitlines():
            if ":" in line and not line.startswith(":"):
                key, _, value = line.partition(":")
                fields[key] = value.removeprefix(" ")
        if "data" in fields:
            out.append(
                (fields.get("event", "message"), fields.get("id"), json.loads(fields["data"]))
            )
    return out


async def login(client: AsyncClient, username: str) -> None:
    response = await client.post("/api/auth/login", json={"username": username, "password": "pw"})
    assert response.status_code == 200


async def client_for(
    app: FastAPI, engine: AsyncEngine, username: str, role: Role = "member"
) -> AsyncClient:
    await create_user(engine, username, "pw", role)
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    await login(client, username)
    return client


async def ask(client: AsyncClient, text: str = "报销上限是多少？") -> tuple[str, str]:
    conv = (await client.post("/api/conversations")).json()
    response = await client.post(f"/api/conversations/{conv['id']}/messages", json={"text": text})
    assert response.status_code == 202
    return conv["id"], response.json()["run_id"]
