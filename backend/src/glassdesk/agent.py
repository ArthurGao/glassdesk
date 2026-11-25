"""The desk agent: one lite-agent `Agent` per run, with read-only knowledge tools (design §5)."""

from collections.abc import Awaitable, Callable, Sequence

from lite_agent import Agent, Budget, SessionStore, ToolContext, tool
from lite_model import AsyncToolModel
from pydantic import BaseModel, Field

from glassdesk.steward import Passage, StewardPort

ROLE = "desk.answer"
NOT_FOUND = "没有找到相关内容。"
PARTIAL = "（部分来源暂时不可用）"
KIND_LABEL = {"memory": "记忆", "entry": "知识条目", "document": "文档"}

SYSTEM = """你是{brand}的知识助手。回答员工的问题时：
- 先用 search_knowledge 搜索，只根据搜索结果回答。
- 引用时在句子后写 [编号]，编号必须与搜索结果里的编号完全一致；不要编造来源或编号。
- 搜索结果里没有相关内容时，直接说没有找到，不要猜测。
- 搜索失败时，告诉用户知识库暂时不可用。
- 用户明确陈述或确认了一条值得团队长期使用的知识时，用 propose_knowledge 提议存入知识库；
  不要提议你自己的推测，也不要提议搜索结果里已经有的内容。
- 用用户提问的语言回答，简洁明了。"""

# (call id, [(citation number, passage), …]): what the page resolves `[n]` against
# propose_knowledge's outcome: (what the model is told, what the timeline shows)
PROPOSED: dict[str, tuple[str, str]] = {
    "awaiting_user": ("已提交，等待你确认。", "待确认"),
    "awaiting_review": ("已提交，等待审核。", "待审核"),
    "entry": ("已存入知识库。", "已存入"),
}

# (call id, steward's retrieval id, [(citation number, passage), …]): what the page resolves
# `[n]` against, and what feedback on an answer is reported under
OnPassages = Callable[[str, str, Sequence[tuple[int, Passage]]], Awaitable[None]]


class SearchArgs(BaseModel):
    query: str = Field(min_length=1, max_length=500, description="要搜索的问题或关键词")


class ProposeArgs(BaseModel):
    title: str = Field(min_length=1, max_length=120, description="知识的标题")
    content: str = Field(min_length=1, max_length=2000, description="知识的完整内容，写成通用表述")
    reason: str = Field(default="", max_length=300, description="为什么值得存入")


def format_passages(passages: Sequence[Passage], degraded: Sequence[str], *, start: int = 1) -> str:
    lines = [PARTIAL] if degraded else []
    if not passages:
        return "\n".join([*lines, NOT_FOUND])
    for n, p in enumerate(passages, start=start):
        lines.append(f"[{n}] {p.title or KIND_LABEL[p.kind]} — {p.text}")
    return "\n".join(lines)


def build_agent(
    *,
    model: AsyncToolModel,
    sessions: SessionStore,
    steward: StewardPort,
    user_id: str,
    brand_name: str,
    on_passages: OnPassages,
    first_n: int = 1,
) -> Agent:
    """Built per run: the tool closes over the asking user, so steward scopes memory to them.
    Citation numbers run on from `first_n` across every search, so `[n]` names one passage in
    the whole conversation, never "the n-th result of some search"."""
    next_n = first_n

    @tool(description="搜索公司知识库和该用户的记忆，返回带编号的段落。")
    async def search_knowledge(args: SearchArgs, ctx: ToolContext) -> str:
        nonlocal next_n
        result = await steward.search(args.query, user_id=user_id, session_id=ctx.session_id)
        start, next_n = next_n, next_n + len(result.passages)
        numbered = list(enumerate(result.passages, start=start))
        await on_passages(ctx.call_id, result.retrieval_id, numbered)
        return format_passages(result.passages, result.degraded, start=start)

    @tool(description="提议把一条知识存入公司知识库。是否生效由知识库的审核规则决定。")
    async def propose_knowledge(args: ProposeArgs, ctx: ToolContext) -> str:
        written = await steward.suggest(
            f"{args.title}\n{args.content}", user_id=user_id, session_id=ctx.session_id
        )
        if written.entry is not None:
            return PROPOSED["entry"][0]
        stage = written.candidate.stage if written.candidate else "awaiting_review"
        return PROPOSED[stage][0]

    return Agent(
        role=ROLE,
        model=model,
        system=SYSTEM.format(brand=brand_name),
        tools=(search_knowledge, propose_knowledge),
        sessions=sessions,
        # Session-wide (lite-agent sums the whole log): a long conversation must not run out.
        budget=Budget(turns=200),
    )
