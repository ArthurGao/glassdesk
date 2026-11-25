"""What glassdesk needs from llm-steward, over its HTTP SDK (never `llm_steward` itself)."""

import logging
from dataclasses import dataclass
from typing import Literal, Protocol

from llm_steward_client import AsyncSteward, StewardError

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Passage:
    item_id: str
    kind: Literal["memory", "entry", "document"]
    title: str | None
    source: str | None  # steward's "memory" or "kb"
    text: str
    score: float
    verified: bool


@dataclass(frozen=True)
class SearchResult:
    retrieval_id: str
    passages: tuple[Passage, ...]
    degraded: tuple[str, ...]  # what steward could not reach; the rest stands


class StewardUnavailable(Exception):
    """steward could not answer. The message never carries steward's own text."""


class StewardPort(Protocol):
    async def search(self, query: str, *, user_id: str, session_id: str) -> SearchResult: ...


class HttpSteward:
    def __init__(self, base_url: str, api_key: str, *, timeout_s: float = 10.0) -> None:
        # One attempt: the agent's tool call is the place a failure becomes visible.
        self._client = AsyncSteward(base_url, api_key, timeout=timeout_s, max_retries=0)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def search(self, query: str, *, user_id: str, session_id: str) -> SearchResult:
        try:
            out = await self._client.retrieve(
                query, user_id=user_id, session_id=session_id, format="items"
            )
        except (StewardError, OSError) as exc:
            log.warning("steward retrieve failed: %s", type(exc).__name__)
            raise StewardUnavailable(type(exc).__name__) from None
        return SearchResult(
            retrieval_id=str(out.retrieval_id),
            passages=tuple(
                Passage(
                    item_id=str(i.id),
                    kind=i.kind,
                    title=i.title,
                    source=i.source,
                    text=i.passages[0] if i.passages else i.content,
                    score=i.score,
                    verified=i.verified,
                )
                for i in out.items
            ),
            degraded=tuple(out.degraded),
        )
