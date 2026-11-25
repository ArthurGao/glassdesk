"""`glassdesk seed --demo`: a fictional company's knowledge, for a demo. Every title starts with
"[演示] " so nobody takes it for the customer's own (KB dates-time-and-metrics §6)."""

from glassdesk.steward import StewardPort

DEMO_PREFIX = "[演示] "

DEMO_ENTRIES: tuple[tuple[str, str], ...] = (
    (
        "差旅住宿标准",
        "示例科技员工国内出差住宿上限：一线城市每晚 800 元，其他城市每晚 500 元；"
        "超出部分需部门负责人审批。",
    ),
    ("报销时限", "费用发生后 30 天内在报销系统提交，附发票原件照片；超过 30 天需财务经理特批。"),
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
)


async def seed_demo(steward: StewardPort) -> int:
    """Write every demo entry steward does not hold yet (live or waiting for review); the count
    written. Running it again writes nothing."""
    held = {e.title for e in await steward.list_entries()}
    held |= {c.title for c in await steward.list_candidates(stage="awaiting_review")}
    written = 0
    for title, content in DEMO_ENTRIES:
        if DEMO_PREFIX + title in held:
            continue
        await steward.create_entry(DEMO_PREFIX + title, content, author="glassdesk-demo")
        written += 1
    return written
