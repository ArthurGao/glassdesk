"""The desk agent: one lite-agent `Agent` per run, with read-only knowledge tools (design §5)."""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import replace
from typing import Annotated

from lite_agent import Agent, Budget, SessionStore, ToolContext, tool
from lite_model import AsyncToolModel
from pydantic import BaseModel, Field, create_model

from glassdesk.i18n import TEXTS, ZH, Texts
from glassdesk.steward import Passage, StewardPort

ROLE = "desk.answer"
# (call id, steward's retrieval id, [(citation number, passage), …]): what the page resolves
# `[n]` against, and what feedback on an answer is reported under
OnPassages = Callable[[str, str, Sequence[tuple[int, Passage]]], Awaitable[None]]


# Each limit is declared once; the descriptions, which the model reads, are per locale.
Query = Annotated[str, Field(min_length=1, max_length=500)]
Title = Annotated[str, Field(min_length=1, max_length=120)]
Content = Annotated[str, Field(min_length=1, max_length=2000)]
Reason = Annotated[str, Field(max_length=300)]


class SearchArgs(BaseModel):
    query: Query


class ProposeArgs(BaseModel):
    title: Title
    content: Content
    reason: Reason = ""


def _arg_models(texts: Texts) -> tuple[type[SearchArgs], type[ProposeArgs]]:
    """The arguments as the model is shown them, described in the locale of the prompt
    (subclasses under the same names, so the tools still receive a SearchArgs / ProposeArgs)."""
    search = create_model(
        "SearchArgs",
        __base__=SearchArgs,
        query=(Query, Field(description=texts.search_query)),
    )
    propose = create_model(
        "ProposeArgs",
        __base__=ProposeArgs,
        title=(Title, Field(description=texts.propose_title)),
        content=(Content, Field(description=texts.propose_content)),
        reason=(Reason, Field(default="", description=texts.propose_reason)),
    )
    return search, propose


_ARGS = {texts: _arg_models(texts) for texts in TEXTS.values()}


def format_passages(
    passages: Sequence[Passage], degraded: Sequence[str], *, start: int = 1, texts: Texts = ZH
) -> str:
    lines = [texts.partial] if degraded else []
    if not passages:
        return "\n".join([*lines, texts.not_found])
    for n, p in enumerate(passages, start=start):
        lines.append(f"[{n}] {p.title or texts.kind_label[p.kind]} — {p.text}")
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
    texts: Texts = ZH,
) -> Agent:
    """Built per run: the tool closes over the asking user, so steward scopes memory to them.
    Citation numbers run on from `first_n` across every search, so `[n]` names one passage in
    the whole conversation, never "the n-th result of some search"."""
    next_n = first_n
    search_args, propose_args = _ARGS[texts]

    @tool(description=texts.search_description)
    async def search_knowledge(args: SearchArgs, ctx: ToolContext) -> str:
        nonlocal next_n
        result = await steward.search(args.query, user_id=user_id, session_id=ctx.session_id)
        start, next_n = next_n, next_n + len(result.passages)
        numbered = list(enumerate(result.passages, start=start))
        await on_passages(ctx.call_id, result.retrieval_id, numbered)
        return format_passages(result.passages, result.degraded, start=start, texts=texts)

    @tool(description=texts.propose_description)
    async def propose_knowledge(args: ProposeArgs, ctx: ToolContext) -> str:
        written = await steward.suggest(
            f"{args.title}\n{args.content}", user_id=user_id, session_id=ctx.session_id
        )
        if written.entry is not None:
            return texts.proposed["entry"][0]
        stage = written.candidate.stage if written.candidate else "awaiting_review"
        return texts.proposed[stage][0]

    return Agent(
        role=ROLE,
        model=model,
        system=texts.system.format(brand=brand_name),
        tools=(
            replace(search_knowledge, model=search_args),
            replace(propose_knowledge, model=propose_args),
        ),
        sessions=sessions,
        # Session-wide (lite-agent sums the whole log): a long conversation must not run out.
        budget=Budget(turns=200),
    )
