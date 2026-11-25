import pytest

from glassdesk.steward import Passage, StewardUnavailable
from glassdesk.testing import FakeSteward

P = Passage(item_id="e1", kind="entry", title="T", source="kb", text="x", score=0.9, verified=True)


async def test_fake_returns_its_passages_and_records_calls() -> None:
    fake = FakeSteward([P], degraded=("rerank",))
    result = await fake.search("q", user_id="u1", session_id="s1")
    assert result.passages == (P,)
    assert result.degraded == ("rerank",)
    assert fake.calls == [("q", "u1", "s1")]


async def test_fake_can_fail_like_an_unreachable_steward() -> None:
    with pytest.raises(StewardUnavailable):
        await FakeSteward(fail=True).search("q", user_id="u1", session_id="s1")
