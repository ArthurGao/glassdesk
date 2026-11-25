"""Test doubles for the boundaries glassdesk does not own (also used by `serve --fake`)."""

from collections.abc import Sequence

from glassdesk.steward import Passage, SearchResult, StewardUnavailable


class FakeSteward:
    """A StewardPort that returns fixed passages and records every search."""

    def __init__(
        self,
        passages: Sequence[Passage] = (),
        *,
        fail: bool = False,
        degraded: tuple[str, ...] = (),
    ) -> None:
        self.passages = tuple(passages)
        self.fail = fail
        self.degraded = degraded
        self.calls: list[tuple[str, str, str]] = []

    async def search(self, query: str, *, user_id: str, session_id: str) -> SearchResult:
        self.calls.append((query, user_id, session_id))
        if self.fail:
            raise StewardUnavailable("ConnectError")
        return SearchResult(
            retrieval_id=f"fake-{len(self.calls)}", passages=self.passages, degraded=self.degraded
        )
