"""`glassdesk seed --demo`: a fictional company's knowledge, for a demo, in the deployment's
locale. Every title starts with the locale's demo prefix ("[演示] ", "[Demo] ") so nobody takes it
for the customer's own (KB dates-time-and-metrics §6)."""

from glassdesk.i18n import ZH, Texts
from glassdesk.steward import StewardPort

DEMO_ENTRIES = ZH.demo_entries


async def seed_demo(steward: StewardPort, *, texts: Texts = ZH) -> int:
    """Write every demo entry steward does not hold yet (live or waiting for review); the count
    written. Running it again writes nothing."""
    held = {e.title for e in await steward.list_entries()}
    held |= {c.title for c in await steward.list_candidates(stage="awaiting_review")}
    written = 0
    for title, content in texts.demo_entries:
        if texts.demo_prefix + title in held:
            continue
        await steward.create_entry(texts.demo_prefix + title, content, author="glassdesk-demo")
        written += 1
    return written
