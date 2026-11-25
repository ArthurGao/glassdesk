"""The agent's event log projected into what the page shows (design §6): steps and cited answers.

Only summaries leave here: never the system prompt, provenance (backends, models, URLs) or raw
tool arguments beyond the search query."""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from lite_agent.events import (
    Event,
    ModelErrorEvent,
    ModelTurn,
    RunFinished,
    TextBlock,
    ToolResultEvent,
    ToolStarted,
    UsageData,
    UserMessage,
)
from pydantic import BaseModel

from glassdesk.steward import Passage

StepKind = Literal["question", "thinking", "tool", "answer", "error", "finished"]
StepStatus = Literal["running", "ok", "error"]
TOOL_TITLES = {"search_knowledge": "搜索知识库"}
_NUMBERED = re.compile(r"^\[\d+\] ", re.MULTILINE)
_MARKER = re.compile(r"\[(\d+)\]")


class Usage(BaseModel):
    input: int | None
    output: int | None
    cost_usd: float | None  # None: the endpoint did not say; never shown as 0


class Step(BaseModel):
    seq: int  # the event that opened the step: the page's key for updating it
    run_id: str
    kind: StepKind
    title: str
    detail: str | None
    status: StepStatus
    started_at: datetime
    duration_ms: int | None
    usage: Usage | None


class Citation(BaseModel):
    n: int
    item_id: str
    kind: str
    title: str | None
    source: str | None
    text: str
    verified: bool


class Answer(BaseModel):
    run_id: str
    text: str
    citations: list[Citation]
    unmatched: list[int]  # markers the model wrote that no search result backs


@dataclass
class _Open:
    step: Step
    last_seq: int  # the newest event this step reflects


def _usage(u: UsageData) -> Usage:
    return Usage(input=u.input, output=u.output, cost_usd=u.cost_usd)


def _ms(start: datetime, end: datetime) -> int:
    return round((end - start).total_seconds() * 1000)


def _clip(text: str, limit: int = 200) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _tool_detail(start: ToolStarted, result: ToolResultEvent | None) -> str | None:
    query = start.arguments.get("query")
    head = f"“{_clip(str(query), 80)}”" if query is not None else None
    if result is None:
        return head
    if result.is_error:
        tail = "失败"
    else:
        found = len(_NUMBERED.findall(result.content))
        tail = f"{found} 条" if found else "没有找到"
    return f"{head} → {tail}" if head else tail


def _project(events: Sequence[Event]) -> list[_Open]:
    steps: list[_Open] = []
    tools: dict[str, _Open] = {}
    starts: dict[str, ToolStarted] = {}
    run_started: dict[str, datetime] = {}
    previous: datetime | None = None

    def add(
        e: Event,
        kind: StepKind,
        title: str,
        *,
        detail: str | None = None,
        status: StepStatus = "ok",
        duration_ms: int | None = None,
        usage: Usage | None = None,
    ) -> None:
        step = Step(
            seq=e.seq,
            run_id=e.run_id,
            kind=kind,
            title=title,
            detail=detail,
            status=status,
            started_at=e.time,
            duration_ms=duration_ms,
            usage=usage,
        )
        steps.append(_Open(step, e.seq))

    for e in events:
        run_started.setdefault(e.run_id, e.time)
        if isinstance(e, UserMessage) and e.origin == "task":
            add(e, "question", "问题", detail=_clip(e.text))
        elif isinstance(e, ModelTurn):
            ends = e.stop != "tool_calls"
            add(
                e,
                "answer" if ends else "thinking",
                "生成回答" if ends else "分析问题",
                duration_ms=_ms(previous, e.time) if previous else None,
                usage=_usage(e.usage),
            )
        elif isinstance(e, ToolStarted):
            add(
                e,
                "tool",
                TOOL_TITLES.get(e.name, e.name),
                status="running",
                detail=_tool_detail(e, None),
            )
            tools[e.call_id], starts[e.call_id] = steps[-1], e
        elif isinstance(e, ToolResultEvent) and e.call_id in tools:
            opened, start = tools.pop(e.call_id), starts.pop(e.call_id)
            opened.step = opened.step.model_copy(
                update={
                    "status": "error" if e.is_error else "ok",
                    "detail": _tool_detail(start, e),
                    "duration_ms": _ms(start.time, e.time),
                }
            )
            opened.last_seq = e.seq
        elif isinstance(e, ModelErrorEvent):
            add(
                e,
                "error",
                "模型调用失败",
                status="error",
                detail=e.error,
                usage=_usage(e.usage) if e.usage else None,
            )
        elif isinstance(e, RunFinished):
            failed = e.outcome == "failed"
            add(
                e,
                "finished",
                "失败" if failed else "完成",
                status="error" if failed else "ok",
                duration_ms=_ms(run_started[e.run_id], e.time),
                usage=_usage(e.usage),
            )
        previous = e.time
    return steps


def project_steps(events: Sequence[Event]) -> list[Step]:
    return [o.step for o in _project(events)]


def steps_after(events: Sequence[Event], after_seq: int) -> list[Step]:
    """Steps that changed after event `after_seq`: new ones, and a tool step whose result came
    later (sent again under its own `seq`, so the page replaces it). In step order."""
    return [o.step for o in _project(events) if o.last_seq > after_seq]


def project_answer(
    events: Sequence[Event], passages_by_call: Mapping[str, Sequence[Passage]], run_id: str
) -> Answer | None:
    """The run's final text with its `[n]` markers resolved, or None until the run finished."""
    mine = [e for e in events if e.run_id == run_id]
    if not any(isinstance(e, RunFinished) for e in mine):
        return None
    turns = [e for e in mine if isinstance(e, ModelTurn) and e.stop != "tool_calls"]
    text = "".join(b.text for b in turns[-1].blocks if isinstance(b, TextBlock)) if turns else ""
    searches = [
        passages_by_call.get(e.call_id, ())
        for e in mine
        if isinstance(e, ToolStarted) and e.name == "search_knowledge"
    ]
    citations: list[Citation] = []
    unmatched: list[int] = []
    for n in dict.fromkeys(int(m) for m in _MARKER.findall(text)):
        # the newest search that returned at least n passages
        hit = next((s[n - 1] for s in reversed(searches) if 1 <= n <= len(s)), None)
        if hit is None:
            unmatched.append(n)
        else:
            citations.append(
                Citation(
                    n=n,
                    item_id=hit.item_id,
                    kind=hit.kind,
                    title=hit.title,
                    source=hit.source,
                    text=hit.text,
                    verified=hit.verified,
                )
            )
    return Answer(run_id=run_id, text=text, citations=citations, unmatched=unmatched)
