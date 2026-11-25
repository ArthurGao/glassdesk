# glassdesk: the SPA built once, served by the backend (one container, one origin).
FROM node:22-slim AS web
RUN corepack enable && corepack prepare pnpm@10.34.7 --activate
WORKDIR /web
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.10.8 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
# llm-steward-client is a git dependency (pinned commit)
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project
COPY backend/src ./src
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim
RUN useradd --system --create-home --uid 10001 glassdesk
COPY --from=build /app/.venv /app/.venv
COPY --from=web /web/dist /app/web
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 GLASSDESK_STATIC_DIR=/app/web
USER glassdesk
WORKDIR /home/glassdesk
EXPOSE 8740
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=5 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8740/api/health', timeout=4)"]
# migrate, make sure the steward collection exists, then serve on every interface of the
# container (the compose file publishes it on the host's loopback only)
CMD ["sh", "-c", "glassdesk migrate && glassdesk setup && exec glassdesk serve --host 0.0.0.0 --port 8740 ${GLASSDESK_SERVE_FLAGS:-}"]
