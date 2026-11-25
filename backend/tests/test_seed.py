from glassdesk.seed import DEMO_ENTRIES, seed_demo
from glassdesk.testing import FakeSteward


async def test_seed_writes_every_demo_entry_labelled_as_demo() -> None:
    steward = FakeSteward()
    written = await seed_demo(steward)
    assert written == len(DEMO_ENTRIES) >= 5
    titles = [e.title for e in steward.entries] + [c.title for c in steward.candidates]
    assert len(titles) == len(DEMO_ENTRIES)
    assert all(t.startswith("[演示] ") for t in titles)


async def test_seed_twice_does_not_duplicate() -> None:
    steward = FakeSteward()
    await seed_demo(steward)
    assert await seed_demo(steward) == 0
    assert len(steward.entries) + len(steward.candidates) == len(DEMO_ENTRIES)
