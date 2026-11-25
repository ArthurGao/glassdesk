"""`glassdesk serve --fake`: the app on a scripted model and a fixed knowledge base, for demos
without a model endpoint and for the e2e tests. Never selected by settings, only by the flag."""

import re

from lite_model import AssistantTurn, Message, Text, ToolCall, ToolResults
from lite_model.testing import AsyncFakeModel, FakeTurnCall

from glassdesk.agent import NOT_FOUND, ROLE
from glassdesk.steward import Passage

DEMO_PASSAGES = (
    Passage(
        item_id="demo-travel",
        kind="entry",
        title="差旅制度 v3",
        source="kb",
        text="国内出差住宿上限每晚 800 元，超出部分需部门负责人审批。",
        score=0.86,
        verified=True,
    ),
    Passage(
        item_id="demo-onboarding",
        kind="document",
        title="入职指南",
        source="kb",
        text="入职当天请携带身份证、学历证明和银行卡，到前台领取工牌。",
        score=0.62,
        verified=False,
    ),
)
_FIRST = re.compile(r"^\[1\] (.+?) — ", re.MULTILINE)


def _reply(call: FakeTurnCall) -> AssistantTurn:
    """Search with the question; once results are back, answer citing the first one."""
    last = call.messages[-1]
    if isinstance(last, ToolResults):
        found = _FIRST.search(last.results[0].content)
        if found is None:
            return AssistantTurn((Text(NOT_FOUND),))
        return AssistantTurn((Text(f"根据《{found.group(1)}》，相关规定见引用[1]。"),))
    question = last.content if isinstance(last, Message) else ""
    n = sum(isinstance(m, ToolResults) for m in call.messages)
    return AssistantTurn((ToolCall(f"demo-{n + 1}", "search_knowledge", {"query": question}),))


def demo_model() -> AsyncFakeModel:
    return AsyncFakeModel(**{ROLE: _reply})
