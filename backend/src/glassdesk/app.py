"""The FastAPI application."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from lite_agent.pg import PgSessionStore
from lite_model import RolePolicy, RoleSpec, build_async

from glassdesk import auth, conversations, kb, suggestions
from glassdesk.agent import ROLE
from glassdesk.config import Settings
from glassdesk.db import Deps, make_engine, sync_url
from glassdesk.runs import Runs
from glassdesk.steward import HttpSteward
from glassdesk.web import register_steward_errors


def _operation_id(route: APIRoute) -> str:
    return route.name


def build_deps(settings: Settings) -> Deps:
    model = build_async(settings.llm, RoleSpec({ROLE: RolePolicy()})) if settings.llm else None
    return Deps(
        engine=make_engine(settings.database_url, settings.db_schema),
        model=model,
        sessions=PgSessionStore(sync_url(settings.database_url), schema=settings.agent_schema),
        steward=HttpSteward.from_settings(settings),
    )


async def close_deps(deps: Deps) -> None:
    if isinstance(deps.steward, HttpSteward):
        await deps.steward.aclose()
    if isinstance(deps.sessions, PgSessionStore):
        await deps.sessions.close()
    aclose = getattr(deps.model, "aclose", None)
    if aclose is not None:
        await aclose()
    await deps.engine.dispose()


def create_app(settings: Settings, *, deps: Deps | None = None) -> FastAPI:
    owned = deps is None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        await app.state.runs.drain()
        if owned:
            await close_deps(app.state.deps)

    app = FastAPI(
        title="glassdesk",
        version="0.1.0",
        lifespan=lifespan,
        # operationId = the handler's name, so the generated TS client reads `login`, `me`, …
        generate_unique_id_function=_operation_id,
    )
    app.state.settings = settings
    app.state.deps = deps if deps is not None else build_deps(settings)
    app.state.runs = Runs()

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    register_steward_errors(app)
    app.include_router(auth.router)
    app.include_router(conversations.router)
    app.include_router(suggestions.router)
    app.include_router(kb.router)
    if settings.static_dir is not None:
        _serve_spa(app, settings.static_dir)
    return app


def _serve_spa(app: FastAPI, root: Path) -> None:
    """The built SPA: its assets, and index.html for every other non-API path (client routes)."""
    index = root / "index.html"
    app.mount("/assets", StaticFiles(directory=root / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "Not Found")
        return FileResponse(index)
