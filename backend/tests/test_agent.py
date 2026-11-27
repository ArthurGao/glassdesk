import asyncio
from collections.abc import Sequence
from dataclasses import replace

import pytest
from lite_agent import Budget, InMemorySessionStore
from lite_agent.events import ToolResultEvent
from lite_model import AssistantTurn, Text, ToolCall
from lite_model.testing import AsyncFakeModel

from glassdesk.agent import ROLE, build_agent, format_passages
from glassdesk.i18n import EN, ZH
from glassdesk.steward import Passage, StewardRejected, StewardUnavailable, Written
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
    assert res.content.splitlines()[0] == "（记忆暂时不可用）"


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
    assert (res.is_error, res.content) == (
        False,
        "已作为提议提交，等待用户确认；它还不在知识库里，也没有经过核实。",
    )
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
    assert res.content == "已作为提议提交，等待审核员审核；它还不在知识库里，也没有经过核实。"


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


async def test_degraded_results_name_what_is_missing() -> None:
    for texts, expected in (
        (ZH, "（记忆、重排序暂时不可用）"),
        (EN, "(memory and reranking unavailable)"),
    ):
        sessions = InMemorySessionStore()
        agent = build_agent(
            model=search_then_answer("q", "a"),
            sessions=sessions,
            steward=FakeSteward([P1], degraded=("rerank", "memory")),
            user_id="u1",
            brand_name="Acme",
            on_passages=Recorded(),
            texts=texts,
        )
        result = await agent.run("q?")
        [res] = await tool_results(sessions, result.session_id)
        assert res.content.splitlines()[0] == expected


def test_every_combination_of_missing_sources_reads_plainly() -> None:
    assert format_passages([], ("kb",), texts=EN).splitlines()[0] == (
        "(knowledge base unavailable)"
    )
    assert format_passages([], ("memory", "kb", "rerank"), texts=EN).splitlines()[0] == (
        "(memory, knowledge base and reranking unavailable)"
    )
    assert format_passages([], ("kb",)).splitlines()[0] == "（知识库暂时不可用）"
    # a source steward may add later is still flagged, without a name we do not know
    assert format_passages([], ("memory", "graph")).splitlines()[0] == "（部分来源暂时不可用）"


def propose_twice_then_answer() -> AsyncFakeModel:
    first = ToolCall("p1", "propose_knowledge", {"title": "报销时限", "content": "30 天内提交"})
    again = ToolCall("p2", "propose_knowledge", {"title": "报销时限", "content": "30 天内提交。"})
    return AsyncFakeModel(
        **{
            ROLE: [
                AssistantTurn((first,)),
                AssistantTurn((again,)),
                AssistantTurn((Text("好的"),)),
            ]
        }
    )


async def test_a_second_proposal_in_one_run_is_refused_without_calling_steward() -> None:
    steward, sessions = FakeSteward(), InMemorySessionStore()
    agent = build_agent(
        model=propose_twice_then_answer(),
        sessions=sessions,
        steward=steward,
        user_id="u1",
        brand_name="Acme",
        on_passages=Recorded(),
    )
    result = await agent.run("记住报销时限")
    assert result.outcome == "completed"
    first, second = await tool_results(sessions, result.session_id)
    assert first.is_error is False
    assert (second.is_error, second.content) == (
        True,
        "AlreadyProposed: 这次回答已经提议过一条知识，不要重复提议。",
    )
    assert len(steward.candidates) == 1


async def test_a_proposal_that_failed_may_be_tried_again_in_the_same_run() -> None:
    class DownOnce(FakeSteward):
        tries = 0

        async def suggest(self, text: str, *, user_id: str, session_id: str) -> Written:
            self.tries += 1
            if self.tries == 1:  # connection refused: the request never reached steward
                raise StewardUnavailable("ConnectError", unsent=True)
            return await super().suggest(text, user_id=user_id, session_id=session_id)

    steward, sessions = DownOnce(), InMemorySessionStore()
    agent = build_agent(
        model=propose_twice_then_answer(),
        sessions=sessions,
        steward=steward,
        user_id="u1",
        brand_name="Acme",
        on_passages=Recorded(),
    )
    result = await agent.run("记住报销时限")
    first, second = await tool_results(sessions, result.session_id)
    assert (first.is_error, second.is_error) == (True, False)
    assert len(steward.candidates) == 1


async def test_proposal_results_say_it_is_not_in_the_knowledge_base_or_verified() -> None:
    class SavesLive(FakeSteward):
        async def suggest(self, text: str, *, user_id: str, session_id: str) -> Written:
            entry = self._entry("t", text, status="active", origin="user_suggestion")
            return Written(entry=entry, candidate=None)

    cases = (
        (FakeSteward(), "Wi-Fi", "awaiting_user"),
        (FakeSteward(), "Pricing", "awaiting_review"),
        (SavesLive(), "Wi-Fi", "entry"),
    )
    seen = {}
    for steward, title, stage in cases:
        sessions = InMemorySessionStore()
        agent = build_agent(
            model=propose_then_answer(title, "c"),
            sessions=sessions,
            steward=steward,
            user_id="u1",
            brand_name="Acme",
            on_passages=Recorded(),
            texts=EN,
        )
        result = await agent.run("remember")
        [res] = await tool_results(sessions, result.session_id)
        seen[stage] = res.content
    assert seen == {
        "awaiting_user": (
            "Submitted as a proposal, waiting for the user's confirmation. It is not in the "
            "knowledge base yet and it is not verified."
        ),
        "awaiting_review": (
            "Submitted as a proposal, waiting for a reviewer. It is not in the knowledge base "
            "yet and it is not verified."
        ),
        "entry": ("Saved to the knowledge base without review: it is not reviewed or verified."),
    }


def test_the_prompt_forbids_calling_a_proposal_verified_or_saved() -> None:
    assert (
        "Never tell the user a proposal is verified or saved unless the tool result says so."
        in EN.system
    )
    assert "除非工具结果明确这样说，否则不要告诉用户提议已经核实或已经存入。" in ZH.system


class FailsFirst(FakeSteward):
    """suggest fails the first time with `error` (or, with `hang`, never answers)."""

    def __init__(self, error: BaseException | None = None, *, hang: bool = False) -> None:
        super().__init__()
        self.error, self.hang, self.tries = error, hang, 0

    async def suggest(self, text: str, *, user_id: str, session_id: str) -> Written:
        self.tries += 1
        if self.tries == 1:
            if self.hang:
                await asyncio.sleep(10)
            assert self.error is not None
            raise self.error
        return await super().suggest(text, user_id=user_id, session_id=session_id)


async def _propose_twice(steward: FailsFirst, *, tool_timeout_s: float | None = None) -> None:
    sessions = InMemorySessionStore()
    agent = build_agent(
        model=propose_twice_then_answer(),
        sessions=sessions,
        steward=steward,
        user_id="u1",
        brand_name="Acme",
        on_passages=Recorded(),
    )
    if tool_timeout_s is not None:
        agent = replace(agent, budget=Budget(turns=200, tool_timeout_s=tool_timeout_s))
    await agent.run("记住报销时限")


@pytest.mark.parametrize(
    "error",
    [
        StewardUnavailable("ServerError"),  # 5xx: steward may have made the candidate
        StewardUnavailable("ReadTimeout"),  # sent, no answer in time
        TimeoutError(),
    ],
)
async def test_a_proposal_that_may_have_reached_steward_is_not_sent_again(
    error: BaseException,
) -> None:
    steward = FailsFirst(error)
    await _propose_twice(steward)
    assert steward.tries == 1


async def test_a_proposal_cancelled_by_the_tool_timeout_is_not_sent_again() -> None:
    steward = FailsFirst(hang=True)
    await _propose_twice(steward, tool_timeout_s=0.05)
    assert steward.tries == 1


async def test_a_proposal_steward_refused_may_be_tried_again() -> None:
    steward = FailsFirst(StewardRejected(422, "title too long"))
    await _propose_twice(steward)
    assert (steward.tries, len(steward.candidates)) == (2, 1)
