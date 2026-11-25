from lite_agent import InMemorySessionStore

from glassdesk.agent import build_agent
from glassdesk.fakes import DEMO_PASSAGES, demo_model
from glassdesk.testing import FakeSteward


async def noop(call_id: str, retrieval_id: str, passages: object) -> None:
    return None


async def test_demo_model_searches_then_cites_for_every_question() -> None:
    steward, sessions = FakeSteward(DEMO_PASSAGES), InMemorySessionStore()
    agent = build_agent(
        model=demo_model(),
        sessions=sessions,
        steward=steward,
        user_id="u1",
        brand_name="Acme",
        on_passages=noop,
    )
    first = await agent.run("报销上限是多少？")
    second = await agent.run("入职要准备什么？", session_id=first.session_id)
    assert [r.outcome for r in (first, second)] == ["completed", "completed"]
    assert [q for q, _, _ in steward.calls] == ["报销上限是多少？", "入职要准备什么？"]
    assert first.text is not None and "[1]" in first.text
    assert DEMO_PASSAGES[0].title is not None and DEMO_PASSAGES[0].title in first.text


async def test_demo_model_says_not_found_when_search_is_empty() -> None:
    agent = build_agent(
        model=demo_model(),
        sessions=InMemorySessionStore(),
        steward=FakeSteward([]),
        user_id="u1",
        brand_name="Acme",
        on_passages=noop,
    )
    result = await agent.run("火星签证？")
    assert result.text == "没有找到相关内容。"


async def test_demo_model_proposes_what_it_is_told_to_remember() -> None:
    steward = FakeSteward(DEMO_PASSAGES)
    agent = build_agent(
        model=demo_model(),
        sessions=InMemorySessionStore(),
        steward=steward,
        user_id="u1",
        brand_name="Acme",
        on_passages=noop,
    )
    result = await agent.run("记住：周五下午不开会")
    assert result.text == "好的，已提交，等待你确认。"
    assert [(c.title, c.requested_for_user) for c in steward.candidates] == [
        ("周五下午不开会", "u1")
    ]
    again = await steward.report_episode(
        [("user", "记住：周五下午不开会")], user_id="u1", session_id="s"
    )
    assert again == []
