"""At most one agent run per conversation, run in the background of the request that asked."""

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable

log = logging.getLogger(__name__)


class Busy(Exception):
    pass


class Runs:
    def __init__(self) -> None:
        self._claimed: set[uuid.UUID] = set()
        self._tasks: set[asyncio.Task[None]] = set()

    def busy(self, conversation_id: uuid.UUID) -> bool:
        return conversation_id in self._claimed

    def claim(self, conversation_id: uuid.UUID) -> None:
        """Synchronous on purpose: no await between the check and the claim."""
        if conversation_id in self._claimed:
            raise Busy(str(conversation_id))
        self._claimed.add(conversation_id)

    def release(self, conversation_id: uuid.UUID) -> None:
        self._claimed.discard(conversation_id)

    def start(self, conversation_id: uuid.UUID, work: Callable[[], Awaitable[None]]) -> None:
        """Run `work` for a claimed conversation; the claim ends when it does."""

        async def go() -> None:
            try:
                await work()
            except Exception:  # the run's own failures are in its event log; this is ours
                log.exception("run for conversation %s raised", conversation_id)
            finally:
                self.release(conversation_id)

        task = asyncio.create_task(go())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def drain(self) -> None:
        """On shutdown: let runs finish their turn rather than cut them mid-way."""
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
