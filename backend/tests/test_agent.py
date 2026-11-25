from collections.abc import Sequence

from lite_agent import InMemorySessionStore
from lite_agent.events import ToolResultEvent
from lite_model import AssistantTurn, Text, ToolCall
from lite_model.testing import AsyncFakeModel

from glassdesk.agent import ROLE, build_agent
from glassdesk.steward import Passage
from glassdesk.testing import FakeSteward

P1 = Passage(
    item_id="e1",
    kind="entry",
    title="差旅制度 v3",
    source="kb",
    text="住宿上限每晚 800 元",
    score=0.9,
    verified=True,
)
P2 = Passage(
    item_id="m1",
    kind="memory",
    title=None,
    source="memory",
    text="用户在上海办公",
    score=0.4,
    verified=False,
)


def search_then_answer(query: str, answer: str) -> AsyncFakeModel:
    return AsyncFakeModel(
        **{
            ROLE: [
                AssistantTurn((ToolCall("c1", "search_knowledge", {"query": query}),)),
                AssistantTurn((Text(answer),)),
            ]
        }
    )


class Recorded:
    def __init__(self) -> None:
        self.seen: list[tuple[str, str, tuple[tuple[int, Passage], ...]]] = []

    async def __call__(
        self, call_id: str, retrieval_id: str, numbered: Sequence[tuple[int, Passage]]
    ) -> None:
        self.seen.append((call_id, retrieval_id, tuple(numbered)))


async def tool_results(
    agent_sessions: InMemorySessionStore, session_id: str
) -> list[ToolResultEvent]:
    return [e for e in await agent_sessions.read(session_id) if isinstance(e, ToolResultEvent)]


async def test_search_tool_passes_user_and_session_and_numbers_results() -> None:
    steward, sessions, recorded = FakeSteward([P1, P2]), InMemorySessionStore(), Recorded()
    agent = build_agent(
        model=search_then_answer("报销上限", "上限 800 元[1]。"),
        sessions=sessions,
        steward=steward,
        user_id="u1",
        brand_name="Acme",
        on_passages=recorded,
    )
    result = await agent.run("报销上限是多少？")
    assert result.outcome == "completed"
    assert result.text == "上限 800 元[1]。"
    assert steward.calls == [("报销上限", "u1", result.session_id)]
    [res] = await tool_results(sessions, result.session_id)
    assert res.is_error is False
    assert res.content.splitlines() == [
        "[1] 差旅制度 v3 — 住宿上限每晚 800 元",
        "[2] 记忆 — 用户在上海办公",
    ]
    assert recorded.seen == [("c1", "fake-1", ((1, P1), (2, P2)))]


async def test_no_results_tool_says_not_found() -> None:
    sessions = InMemorySessionStore()
    agent = build_agent(
        model=search_then_answer("火星", "没有找到。"),
        sessions=sessions,
        steward=FakeSteward([]),
        user_id="u1",
        brand_name="Acme",
        on_passages=Recorded(),
    )
    result = await agent.run("火星签证？")
    [res] = await tool_results(sessions, result.session_id)
    assert res.content == "没有找到相关内容。"


async def test_degraded_results_say_some_sources_are_missing() -> None:
    sessions = InMemorySessionStore()
    agent = build_agent(
        model=search_then_answer("q", "a"),
        sessions=sessions,
        steward=FakeSteward([P1], degraded=("memory",)),
        user_id="u1",
        brand_name="Acme",
        on_passages=Recorded(),
    )
    result = await agent.run("q?")
    [res] = await tool_results(sessions, result.session_id)
    assert res.content.splitlines()[0] == "（部分来源暂时不可用）"


async def test_steward_down_gives_error_tool_result_and_run_completes() -> None:
    sessions, recorded = InMemorySessionStore(), Recorded()
    agent = build_agent(
        model=search_then_answer("q", "知识库暂时不可用。"),
        sessions=sessions,
        steward=FakeSteward(fail=True),
        user_id="u1",
        brand_name="Acme",
        on_passages=recorded,
    )
    result = await agent.run("q?")
    assert result.outcome == "completed"
    [res] = await tool_results(sessions, result.session_id)
    assert res.is_error is True
    assert res.content == "StewardUnavailable: ConnectError"
    assert recorded.seen == []


def propose_then_answer(title: str, content: str) -> AsyncFakeModel:
    call = ToolCall(
        "p1", "propose_knowledge", {"title": title, "content": content, "reason": "用户要求"}
    )
    return AsyncFakeModel(**{ROLE: [AssistantTurn((call,)), AssistantTurn((Text("好的"),))]})


async def test_the_agent_offers_search_and_propose() -> None:
    agent = build_agent(
        model=AsyncFakeModel(),
        sessions=InMemorySessionStore(),
        steward=FakeSteward(),
        user_id="u1",
        brand_name="Acme",
        on_passages=Recorded(),
    )
    assert [t.name for t in agent.tools] == ["search_knowledge", "propose_knowledge"]
    assert "propose_knowledge" in agent.system


async def test_propose_becomes_a_card_for_the_user() -> None:
    steward, sessions = FakeSteward(), InMemorySessionStore()
    agent = build_agent(
        model=propose_then_answer("报销时限", "30 天内提交"),
        sessions=sessions,
        steward=steward,
        user_id="u1",
        brand_name="Acme",
        on_passages=Recorded(),
    )
    result = await agent.run("记住报销时限")
    [res] = await tool_results(sessions, result.session_id)
    assert (res.is_error, res.content) == (False, "已提交，等待你确认。")
    [card] = steward.candidates
    assert (card.title, card.content, card.requested_for_user) == ("报销时限", "30 天内提交", "u1")


async def test_a_high_risk_proposal_waits_for_review() -> None:
    sessions = InMemorySessionStore()
    agent = build_agent(
        model=propose_then_answer("新价格", "A 套餐 99 元"),
        sessions=sessions,
        steward=FakeSteward(),
        user_id="u1",
        brand_name="Acme",
        on_passages=Recorded(),
    )
    result = await agent.run("记住新价格")
    [res] = await tool_results(sessions, result.session_id)
    assert res.content == "已提交，等待审核。"


async def test_a_proposal_when_steward_is_down_is_an_error_result() -> None:
    sessions = InMemorySessionStore()
    agent = build_agent(
        model=propose_then_answer("t", "c"),
        sessions=sessions,
        steward=FakeSteward(fail=True),
        user_id="u1",
        brand_name="Acme",
        on_passages=Recorded(),
    )
    result = await agent.run("记住")
    [res] = await tool_results(sessions, result.session_id)
    assert (res.is_error, result.outcome) == (True, "completed")
