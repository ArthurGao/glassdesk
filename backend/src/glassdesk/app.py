"""The FastAPI application."""

from fastapi import FastAPI

from glassdesk.config import Settings


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title="glassdesk", version="0.1.0")
    app.state.settings = settings

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
