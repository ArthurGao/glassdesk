"""At most one agent run per conversation, run in the background of the request that asked.

A run holds its conversation's claim only while the agent works; reporting its episode to
steward afterwards (another model call there) runs without the claim, so the next question is
not held up, and streams follow it through `following`."""

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable

log = logging.getLogger(__name__)


class Busy(Exception):
    pass


class Runs:
    def __init__(self) -> None:
        self._claims: dict[uuid.UUID, str] = {}  # conversation -> the run holding it
        self._after: dict[uuid.UUID, int] = {}  # conversation -> work still going after runs
        self._tasks: set[asyncio.Task[None]] = set()
        # conversation -> the run that ended without writing its end (raised, store gone)
        self.failed: dict[uuid.UUID, str] = {}

    def busy(self, conversation_id: uuid.UUID) -> bool:
        """A run holds the conversation: a new question would be refused."""
        return conversation_id in self._claims

    def following(self, conversation_id: uuid.UUID) -> bool:
        """Something a stream should still wait for: a run, or the work after one."""
        return self.busy(conversation_id) or self._after.get(conversation_id, 0) > 0

    def claim(self, conversation_id: uuid.UUID, run_id: str) -> None:
        """Synchronous on purpose: no await between the check and the claim."""
        if conversation_id in self._claims:
            raise Busy(str(conversation_id))
        self._claims[conversation_id] = run_id
        self.failed.pop(conversation_id, None)

    def release(self, conversation_id: uuid.UUID, run_id: str) -> None:
        """Only the run that holds the claim ends it: a later run's claim is left alone."""
        if self._claims.get(conversation_id) == run_id:
            del self._claims[conversation_id]

    def start(
        self,
        conversation_id: uuid.UUID,
        run_id: str,
        work: Callable[[], Awaitable[None]],
        after: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        """Run `work` under the claim, then `after` without it (still followed by streams)."""

        async def go() -> None:
            self._after[conversation_id] = self._after.get(conversation_id, 0) + 1
            try:
                try:
                    await work()
                finally:
                    self.release(conversation_id, run_id)
                if after is not None:
                    await after()
            except Exception:  # the run's own failures are in its event log; this is ours
                log.exception("run %s of conversation %s raised", run_id, conversation_id)
            finally:
                self._after[conversation_id] -= 1

        task = asyncio.create_task(go())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def drain(self) -> None:
        """On shutdown: let runs finish their turn rather than cut them mid-way."""
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
