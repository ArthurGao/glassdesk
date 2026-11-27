"""User-facing copy per deployment locale (GLASSDESK_LOCALE, design §8). zh is the default and holds
the copy glassdesk shipped with; en mirrors it key for key."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from starlette.requests import Request

Locale = Literal["zh", "en"]


@dataclass(frozen=True, eq=False)  # hashed by identity: one instance per locale
class Texts:
    # The agent: its prompt, its tools, and what the tools tell the model
    system: str  # formatted with {brand}
    search_description: str
    search_query: str
    propose_description: str
    propose_title: str
    propose_content: str
    propose_reason: str
    not_found: str
    # partial and proposed[…][0] are stored in event logs and parsed back by the timeline: editing
    # them leaves old logs unrecognised (ANY_PARTIAL / ANY_PROPOSED only know the current wording).
    partial: str  # the first line of a search result when some source was down
    kind_label: dict[str, str]
    # propose_knowledge's outcome: (what the model is told, what the timeline shows)
    proposed: dict[str, tuple[str, str]]
    # The timeline
    tool_titles: dict[str, str]
    step_question: str
    step_thinking: str
    step_answer: str
    step_model_error: str
    step_done: str
    failed: str
    submitted: str  # a proposal whose outcome the timeline does not recognise
    found: Callable[[int], str]
    none_found: str
    partial_tail: str
    # Conversations
    new_title: str
    failed_message: str
    # HTTP error details (the page shows the upload ones; the rest serve other API clients)
    upload_types: str
    upload_too_big: str
    upload_empty: str
    not_configured: str
    kb_not_configured: str
    kb_unavailable: str
    busy: str
    already_decided: str
    needs_reviewer: str
    wrong_login: str
    # The demo seed (titles start with demo_prefix, so nobody takes them for the customer's own)
    demo_prefix: str
    demo_entries: tuple[tuple[str, str], ...]


ZH = Texts(
    system="""你是{brand}的知识助手。回答员工的问题时：
- 先用 search_knowledge 搜索，只根据搜索结果回答。
- 引用时在句子后写 [编号]，编号必须与搜索结果里的编号完全一致；不要编造来源或编号。
- 搜索结果里没有相关内容时，直接说没有找到，不要猜测。
- 搜索失败时，告诉用户知识库暂时不可用。
- 用户明确陈述或确认了一条值得团队长期使用的知识时，用 propose_knowledge 提议存入知识库；
  不要提议你自己的推测，也不要提议搜索结果里已经有的内容。
- 用用户提问的语言回答，简洁明了。""",
    search_description="搜索公司知识库和该用户的记忆，返回带编号的段落。",
    search_query="要搜索的问题或关键词",
    propose_description="提议把一条知识存入公司知识库。是否生效由知识库的审核规则决定。",
    propose_title="知识的标题",
    propose_content="知识的完整内容，写成通用表述",
    propose_reason="为什么值得存入",
    not_found="没有找到相关内容。",
    partial="（部分来源暂时不可用）",
    kind_label={"memory": "记忆", "entry": "知识条目", "document": "文档"},
    proposed={
        "awaiting_user": ("已提交，等待你确认。", "待确认"),
        "awaiting_review": ("已提交，等待审核。", "待审核"),
        "entry": ("已存入知识库。", "已存入"),
    },
    tool_titles={"search_knowledge": "搜索知识库", "propose_knowledge": "提议存入知识库"},
    step_question="问题",
    step_thinking="分析问题",
    step_answer="生成回答",
    step_model_error="模型调用失败",
    step_done="完成",
    failed="失败",
    submitted="已提交",
    found=lambda n: f"{n} 条",
    none_found="没有找到",
    partial_tail="（部分结果）",
    new_title="新会话",
    failed_message="这次回答没有完成，请重试。",
    upload_types="只支持 PDF、Word、Markdown、TXT、HTML 文件",
    upload_too_big="文件不能超过 20 MB",
    upload_empty="文件是空的",
    not_configured="模型或知识库未配置",
    kb_not_configured="知识库未配置",
    kb_unavailable="知识库暂时不可用",
    busy="上一个问题还在处理中",
    already_decided="已处理",
    needs_reviewer="需要审核权限",
    wrong_login="用户名或密码错误",
    demo_prefix="[演示] ",
    demo_entries=(
        (
            "差旅住宿标准",
            "示例科技员工国内出差住宿上限：一线城市每晚 800 元，其他城市每晚 500 元；"
            "超出部分需部门负责人审批。",
        ),
        (
            "报销时限",
            "费用发生后 30 天内在报销系统提交，附发票原件照片；超过 30 天需财务经理特批。",
        ),
        ("年假规则", "入职满一年享 5 天年假，满五年 10 天；当年未休年假可顺延到次年 3 月 31 日。"),
        (
            "入职第一天",
            "入职当天 9:30 到前台报到，携带身份证、学历证明和银行卡；IT 会在当天发放电脑和账号。",
        ),
        ("会议室预订", "会议室在协作平台「会议室」页预订，单次最长 2 小时；取消需提前 30 分钟。"),
        (
            "产品价格（需审核）",
            "示例科技标准版每用户每月 99 元，企业版另议。价格类内容按规定需审核后生效。",
        ),
    ),
)

EN = Texts(
    system="""You are {brand}'s knowledge assistant. When answering an employee's question:
- Search with search_knowledge first, and answer only from the search results.
- When citing, write [number] after the sentence; the number must match a number in the search
  results exactly. Never invent sources or numbers.
- When the search results hold nothing relevant, say you found nothing. Do not guess.
- When the search fails, tell the user the knowledge base is unavailable for now.
- When the user clearly states or confirms knowledge the team should keep, propose it with
  propose_knowledge. Do not propose your own guesses, or what the search results already hold.
- Answer in the language of the user's question, briefly and clearly.""",
    search_description=(
        "Search the company knowledge base and this user's memories; returns numbered passages."
    ),
    search_query="The question or keywords",
    propose_description=(
        "Propose saving a piece of knowledge to the company knowledge base. "
        "The knowledge base's review rules decide whether it goes live."
    ),
    propose_title="The knowledge's title",
    propose_content="The knowledge in full, phrased generally",
    propose_reason="Why it is worth keeping",
    not_found="No relevant content found.",
    partial="(Some sources are unavailable for now)",
    kind_label={"memory": "Memory", "entry": "Knowledge entry", "document": "Document"},
    proposed={
        "awaiting_user": (
            "Submitted, waiting for your confirmation.",
            "Awaiting your confirmation",
        ),
        "awaiting_review": ("Submitted, waiting for review.", "Awaiting review"),
        "entry": ("Saved to the knowledge base.", "Saved"),
    },
    tool_titles={
        "search_knowledge": "Searching the knowledge base",
        "propose_knowledge": "Proposing to the knowledge base",
    },
    step_question="Question",
    step_thinking="Analyzing the question",
    step_answer="Writing the answer",
    step_model_error="Model call failed",
    step_done="Done",
    failed="Failed",
    submitted="Submitted",
    found=lambda n: f"{n} result" if n == 1 else f"{n} results",
    none_found="nothing found",
    partial_tail=" (partial)",
    new_title="New conversation",
    failed_message="This answer did not finish. Please try again.",
    upload_types="Only PDF, Word, Markdown, TXT and HTML files are supported",
    upload_too_big="Files must not exceed 20 MB",
    upload_empty="The file is empty",
    not_configured="The model or knowledge base is not configured",
    kb_not_configured="The knowledge base is not configured",
    kb_unavailable="The knowledge base is unavailable for now",
    busy="The previous question is still being answered",
    already_decided="Already decided",
    needs_reviewer="Reviewer permission required",
    wrong_login="Wrong username or password",
    demo_prefix="[Demo] ",
    demo_entries=(
        (
            "Travel lodging limits",
            "Example Tech staff on domestic trips may spend up to 800 CNY a night in tier-1 cities "
            "and 500 CNY elsewhere; anything above needs the department head's approval.",
        ),
        (
            "Expense claim deadline",
            "Submit claims in the expense system within 30 days, with a photo of the original "
            "invoice; after 30 days the finance manager must approve.",
        ),
        (
            "Annual leave",
            "After one year: 5 days of annual leave; after five years: 10. Unused leave carries "
            "over until 31 March of the next year.",
        ),
        (
            "Your first day",
            "Report to reception at 9:30 with your ID, degree certificate and bank card; IT hands "
            "out your laptop and accounts the same day.",
        ),
        (
            "Booking meeting rooms",
            "Book rooms on the collaboration platform's Rooms page, for up to 2 hours at a time; "
            "cancel at least 30 minutes ahead.",
        ),
        (
            "Product pricing (needs review)",
            "Example Tech Standard costs 99 CNY per user per month; Enterprise is quoted. Pricing "
            "content must be reviewed before it goes live.",
        ),
    ),
)

TEXTS: dict[Locale, Texts] = {"zh": ZH, "en": EN}

# What a tool result may say, in any locale: event logs outlive a locale switch.
ANY_PARTIAL = tuple(t.partial for t in TEXTS.values())
ANY_PROPOSED = {
    t.proposed[stage][0]: stage for t in TEXTS.values() for stage in t.proposed
}  # model text -> stage


def texts_for(request: Request) -> Texts:
    """The copy of the deployment serving `request`."""
    texts: Texts = TEXTS[request.app.state.settings.locale]
    return texts
