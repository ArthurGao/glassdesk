"""GLASSDESK_LOCALE: a deployment's UI language (zh default, en). zh keeps today's copy exactly."""

from collections.abc import Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from lite_agent import InMemorySessionStore
from lite_agent.events import Event, RunStarted, ToolResultEvent, ToolStarted
from lite_model import AssistantTurn, Text, ToolCall
from lite_model.testing import AsyncFakeModel
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncEngine

from glassdesk.agent import ROLE, build_agent
from glassdesk.app import create_app
from glassdesk.config import Settings
from glassdesk.db import Deps
from glassdesk.i18n import TEXTS
from glassdesk.seed import seed_demo
from glassdesk.testing import FakeSteward
from glassdesk.timeline import project_steps
from tests.helpers import client_for, search_then_answer
from tests.test_timeline import env, run_events


def _settings(**update: object) -> Settings:
    return Settings(
        database_url="postgresql+psycopg://u:p@h/d",
        steward_api_key="k",  # type: ignore[arg-type]
        steward_review_key="r",  # type: ignore[arg-type]
        session_secret="s" * 32,  # type: ignore[arg-type]
        _env_file=None,  # type: ignore[call-arg]
        **update,  # type: ignore[arg-type]
    )


def test_locale_defaults_to_zh_and_only_takes_zh_or_en(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GLASSDESK_LOCALE", raising=False)
    assert _settings().locale == "zh"
    assert _settings(locale="en").locale == "en"
    with pytest.raises(ValidationError):
        _settings(locale="fr")


def test_branding_tells_the_page_the_locale(settings: Settings, deps: Deps) -> None:
    english = settings.model_copy(update={"locale": "en"})
    assert TestClient(create_app(english, deps=deps)).get("/api/branding").json()["locale"] == "en"


def _proposal(content: str, seq: int = 5) -> list[Event]:
    args = {"title": "Wi-Fi", "content": "pw", "reason": ""}
    return [
        ToolStarted(call_id="p1", name="propose_knowledge", arguments=args, **env(seq)),
        ToolResultEvent(
            call_id="p1", content=content, executed=True, original_chars=9, **env(seq + 1, ms=5)
        ),
    ]


def test_steps_read_in_english_under_en() -> None:
    steps = project_steps(run_events(), texts=TEXTS["en"])
    assert [s.title for s in steps] == [
        "Question",
        "Analyzing the question",
        "Searching the knowledge base",
        "Writing the answer",
        "Done",
    ]
    assert steps[2].detail == "“报销” → 2 results"
    [proposed] = project_steps(
        _proposal(TEXTS["en"].proposed["awaiting_review"][0]), texts=TEXTS["en"]
    )
    assert proposed.title == "Proposing to the knowledge base"
    assert proposed.detail == "“Wi-Fi” → Awaiting review"


def test_zh_steps_are_unchanged() -> None:
    steps = project_steps(run_events())
    assert [s.title for s in steps] == ["问题", "分析问题", "搜索知识库", "生成回答", "完成"]
    [proposed] = project_steps(_proposal("已提交，等待审核。"))
    assert proposed.detail == "“Wi-Fi” → 待审核"


def test_a_log_recorded_under_zh_still_reads_under_en() -> None:
    """Event logs outlive a locale switch: zh tool results are recognised and labelled in en."""
    [proposed] = project_steps(_proposal("已提交，等待审核。"), texts=TEXTS["en"])
    assert proposed.detail == "“Wi-Fi” → Awaiting review"
    events = run_events()
    search_result = events[5]
    assert isinstance(search_result, ToolResultEvent)
    events[5] = search_result.model_copy(
        update={"content": "（部分来源暂时不可用）\n[1] T1 — text 1"}
    )
    assert project_steps(events, texts=TEXTS["en"])[2].detail == "“报销” → 1 result (partial)"


async def test_the_agent_is_prompted_and_told_results_in_english_under_en() -> None:
    sessions = InMemorySessionStore()
    model = AsyncFakeModel(
        **{
            ROLE: [
                AssistantTurn((ToolCall("c1", "search_knowledge", {"query": "wifi"}),)),
                AssistantTurn((Text("Not found."),)),
            ]
        }
    )

    async def ignore(*_: object) -> None:
        return None

    agent = build_agent(
        model=model,
        sessions=sessions,
        steward=FakeSteward([]),
        user_id="u1",
        brand_name="Acme",
        on_passages=ignore,
        texts=TEXTS["en"],
    )
    result = await agent.run("wifi password?")
    events = await sessions.read(result.session_id)
    [started] = [e for e in events if isinstance(e, RunStarted)]
    assert started.system.startswith("You are Acme's knowledge assistant.")
    [found] = [e for e in events if isinstance(e, ToolResultEvent)]
    assert found.content == "No relevant content found."
    search = next(t for t in model.turn_calls[0].tools if t.name == "search_knowledge")
    assert search.description.startswith("Search the company knowledge base")
    assert search.parameters["properties"]["query"]["description"] == "The question or keywords"


async def test_errors_and_new_titles_are_english_under_en(
    make_app: Callable[..., FastAPI], engine: AsyncEngine
) -> None:
    client = await client_for(make_app(search_then_answer("a"), locale="en"), engine, "alice")
    conv = (await client.post("/api/conversations")).json()
    assert conv["title"] == "New conversation"
    exe = await client.post("/api/kb/documents", files={"file": ("a.exe", b"MZ", "application/x")})
    assert exe.json()["detail"] == "Only PDF, Word, Markdown, TXT and HTML files are supported"
    await client.post("/api/auth/logout")
    wrong = await client.post("/api/auth/login", json={"username": "alice", "password": "no"})
    assert wrong.json()["detail"] == "Wrong username or password"


async def test_english_demo_seed_is_marked_as_demo() -> None:
    steward = FakeSteward()
    assert await seed_demo(steward, texts=TEXTS["en"]) >= 5
    titles = [e.title for e in steward.entries] + [c.title for c in steward.candidates]
    assert titles and all(t.startswith("[Demo] ") for t in titles)


async def test_english_demo_pricing_waits_for_review_like_the_chinese_one() -> None:
    """steward's review gate is a keyword list: English deployments need English keywords."""
    steward = FakeSteward()
    await seed_demo(steward, texts=TEXTS["en"])
    assert [c.title for c in steward.candidates] == ["[Demo] Product pricing (needs review)"]
    assert len(steward.entries) == len(TEXTS["en"].demo_entries) - 1
