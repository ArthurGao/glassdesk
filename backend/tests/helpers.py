"""Shared test builders."""

import asyncio
import json
from typing import Any

from httpx import AsyncClient
from lite_model import AssistantTurn, Text, ToolCall
from lite_model.testing import AsyncFakeModel

from glassdesk.agent import ROLE
from glassdesk.steward import Passage

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
