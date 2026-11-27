import json
from datetime import UTC, datetime, timedelta

from lite_agent.events import (
    Event,
    ModelTurn,
    ProvenanceData,
    RunFinished,
    RunStarted,
    SessionStarted,
    TextBlock,
    ToolCallBlock,
    ToolResultEvent,
    ToolStarted,
    UsageData,
    UserMessage,
)

from glassdesk.i18n import EN, ZH
from glassdesk.steward import Passage
from glassdesk.timeline import project_answer, project_steps, steps_after

T0 = datetime(2026, 11, 25, 9, 0, tzinfo=UTC)
PROV = ProvenanceData(
    role="desk.answer",
    backend="ollama",
    requested="qwen3:8b",
    answered="qwen3:8b",
    channel="local",
    routed=False,
)


def env(seq: int, run: str = "r1", ms: int = 0) -> dict[str, object]:
    return {"session_id": "s1", "seq": seq, "run_id": run, "time": T0 + timedelta(milliseconds=ms)}


def passage(n: int) -> Passage:
    return Passage(
        item_id=f"e{n}",
        kind="entry",
        title=f"T{n}",
        source="kb",
        text=f"text {n}",
        score=0.9,
        verified=n == 1,
    )


def run_events(answer: str = "上限 800 元[1]。", cost: float | None = 0.002) -> list[Event]:
    return [
        SessionStarted(**env(1)),
        RunStarted(role="desk.answer", system="SECRET-PROMPT", tools=(), **env(2)),
        UserMessage(text="报销上限？", **env(3)),
        ModelTurn(
            blocks=(ToolCallBlock(id="c1", name="search_knowledge", arguments={"query": "报销"}),),
            stop="tool_calls",
            role="desk.answer",
            provenance=PROV,
            usage=UsageData(input=100, output=10),
            **env(4, ms=400),
        ),
        ToolStarted(
            call_id="c1", name="search_knowledge", arguments={"query": "报销"}, **env(5, ms=410)
        ),
        ToolResultEvent(
            call_id="c1",
            content="[1] T1 — text 1\n[2] T2 — text 2",
            executed=True,
            original_chars=30,
            **env(6, ms=610),
        ),
        ModelTurn(
            blocks=(TextBlock(text=answer),),
            stop="end",
            role="desk.answer",
            provenance=PROV,
            usage=UsageData(input=300, output=40),
            **env(7, ms=2610),
        ),
        RunFinished(
            outcome="completed",
            stop="end_turn",
            usage=UsageData(input=400, output=50, cost_usd=cost),
            **env(8, ms=2620),
        ),
    ]


def test_steps_pair_tool_calls_and_hide_system_prompt() -> None:
    steps = project_steps(run_events())
    assert [s.kind for s in steps] == ["question", "thinking", "tool", "answer", "finished"]
    tool = steps[2]
    assert (tool.seq, tool.title, tool.status, tool.duration_ms) == (5, "搜索知识库", "ok", 200)
    assert tool.detail == "“报销” → 2 条"
    assert steps[-1].usage is not None and steps[-1].usage.input == 400
    dumped = json.dumps([s.model_dump(mode="json") for s in steps], ensure_ascii=False)
    assert "SECRET-PROMPT" not in dumped
    assert "ollama" not in dumped and "qwen3" not in dumped


def test_a_tool_without_result_is_running_and_an_error_result_is_error() -> None:
    events = run_events()[:5]
    assert project_steps(events)[-1].status == "running"
    failed = [
        *events,
        ToolResultEvent(
            call_id="c1",
            content="StewardUnavailable: ConnectError",
            is_error=True,
            error_kind="exception",
            executed=True,
            original_chars=10,
            **env(6, ms=500),
        ),
    ]
    step = project_steps(failed)[-1]
    assert (step.status, step.detail) == ("error", "“报销” → 失败")


def test_unknown_cost_stays_null() -> None:
    finished = project_steps(run_events(cost=None))[-1]
    assert finished.usage is not None and finished.usage.cost_usd is None


def test_answer_maps_markers_and_reports_unmatched() -> None:
    events = run_events(answer="上限 800 元[1]，需审批[3]，见[1]。")
    answer = project_answer(events, {1: passage(1), 2: passage(2)}, "r1")
    assert answer is not None
    assert answer.question == "报销上限？"
    assert answer.text == "上限 800 元[1]，需审批[3]，见[1]。"
    assert [(c.n, c.item_id, c.text, c.verified) for c in answer.citations] == [
        (1, "e1", "text 1", True)
    ]
    assert answer.unmatched == [3]


def test_answer_without_markers_has_no_citations() -> None:
    answer = project_answer(run_events(answer="没有找到。"), {1: passage(1)}, "r1")
    assert answer is not None and answer.citations == [] and answer.unmatched == []


def test_an_unfinished_run_has_no_answer() -> None:
    assert project_answer(run_events()[:6], {1: passage(1)}, "r1") is None


def test_steps_after_a_cut_between_tool_start_and_result_resend_the_tool_step() -> None:
    events = run_events()
    first = steps_after(events[:5], 0)
    assert [(s.kind, s.status) for s in first][-1] == ("tool", "running")
    rest = steps_after(events, 5)
    assert [(s.seq, s.kind, s.status) for s in rest] == [
        (5, "tool", "ok"),
        (7, "answer", "ok"),
        (8, "finished", "ok"),
    ]


def test_steps_after_the_end_are_empty() -> None:
    assert steps_after(run_events(), 8) == []


def test_a_degraded_search_is_marked_partial() -> None:
    events = run_events()
    result = events[5]
    assert isinstance(result, ToolResultEvent)
    events[5] = result.model_copy(update={"content": "（部分来源暂时不可用）\n" + result.content})
    tool = project_steps(events)[2]
    assert tool.detail == "“报销” → 2 条（部分结果）"


def test_a_failed_run_has_a_failed_answer() -> None:
    finished = RunFinished(outcome="failed", stop="error", usage=UsageData(), **env(7, ms=900))
    events = [*run_events()[:6], finished]
    answer = project_answer(events, {}, "r1")
    assert answer is not None
    assert (answer.failed, answer.text) == (True, "")


def test_a_proposal_step_shows_its_title_and_outcome() -> None:
    events: list[Event] = [
        RunStarted(role="desk.answer", system="s", tools=(), **env(2)),
        ToolStarted(
            call_id="p1",
            name="propose_knowledge",
            arguments={"title": "报销时限", "content": "30 天", "reason": ""},
            **env(3),
        ),
        ToolResultEvent(
            call_id="p1",
            content="已提交，等待你确认。",
            executed=True,
            original_chars=10,
            **env(4, ms=100),
        ),
    ]
    [step] = project_steps(events)
    assert (step.title, step.detail, step.status) == ("提议存入知识库", "“报销时限” → 待确认", "ok")


def test_a_search_step_says_how_many_results_came_from_the_kb_and_from_memory() -> None:
    kinds = {("r1", "c1"): {"entry": 4, "document": 1, "memory": 3}}
    assert project_steps(run_events(), kinds=kinds)[2].detail == (
        "“报销” → 8 条：知识库 5 条，记忆 3 条"
    )
    assert project_steps(run_events(), kinds=kinds, texts=EN)[2].detail == (
        "“报销” → 8 results: 5 from the knowledge base, 3 from memory"
    )
    only_kb = {("r1", "c1"): {"entry": 2}}
    assert project_steps(run_events(), kinds=only_kb, texts=EN)[2].detail == (
        "“报销” → 2 results: 2 from the knowledge base"
    )
    # the stream resends the step under the same kinds
    [tool, *_] = steps_after(run_events(), 5, kinds={("r1", "c1"): {"memory": 2}})
    assert tool.detail == "“报销” → 2 条：记忆 2 条"


def test_a_degraded_search_says_what_was_missing() -> None:
    events = run_events()
    result = events[5]
    assert isinstance(result, ToolResultEvent)
    events[5] = result.model_copy(
        update={"content": "（记忆、重排序暂时不可用）\n" + result.content}
    )
    kinds = {("r1", "c1"): {"entry": 2}}
    assert project_steps(events, kinds=kinds)[2].detail == (
        "“报销” → 2 条：知识库 2 条（记忆、重排序暂时不可用）"
    )
    # recorded in zh, read in en
    assert project_steps(events, kinds=kinds, texts=EN)[2].detail == (
        "“报销” → 2 results: 2 from the knowledge base (memory and reranking unavailable)"
    )


def test_a_refused_second_proposal_is_not_shown_as_a_failure() -> None:
    events: list[Event] = [
        RunStarted(role="desk.answer", system="s", tools=(), **env(2)),
        ToolStarted(
            call_id="p2",
            name="propose_knowledge",
            arguments={"title": "报销时限", "content": "30 天", "reason": ""},
            **env(3),
        ),
        ToolResultEvent(
            call_id="p2",
            content="AlreadyProposed: 这次回答已经提议过一条知识，不要重复提议。",
            is_error=True,
            error_kind="exception",
            executed=True,
            original_chars=10,
            **env(4, ms=1),
        ),
    ]
    [step] = project_steps(events)
    assert (step.status, step.detail) == ("ok", "“报销时限” → 已提议过，未重复提交")


def test_new_proposal_wording_still_maps_to_its_stage() -> None:
    for stage, shown in (("awaiting_user", "待确认"), ("entry", "已存入（未审核）")):
        events: list[Event] = [
            ToolStarted(call_id="p1", name="propose_knowledge", arguments={"title": "t"}, **env(3)),
            ToolResultEvent(
                call_id="p1",
                content=ZH.proposed[stage][0],
                executed=True,
                original_chars=10,
                **env(4),
            ),
        ]
        assert project_steps(events)[0].detail == f"“t” → {shown}"
