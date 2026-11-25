import asyncio
import uuid

import pytest

from glassdesk.runs import Busy, Runs


async def test_a_claim_waits_briefly_for_a_run_that_is_just_finishing() -> None:
    """The answer is visible as soon as the run writes its end; the claim is released a moment
    later. A question asked in between must not be refused."""
    runs, conv = Runs(), uuid.uuid4()
    runs.claim(conv, "a")

    async def finish_soon() -> None:
        await asyncio.sleep(0.05)
        runs.release(conv, "a")

    task = asyncio.create_task(finish_soon())
    await runs.claim_waiting(conv, "b", timeout_s=1.0)
    await task
    assert runs.busy(conv)
    runs.release(conv, "b")
    assert not runs.busy(conv)


async def test_a_claim_still_refuses_a_run_that_keeps_going() -> None:
    runs, conv = Runs(), uuid.uuid4()
    runs.claim(conv, "a")
    with pytest.raises(Busy):
        await runs.claim_waiting(conv, "b", timeout_s=0.05)
