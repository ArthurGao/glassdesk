# glassdesk

A knowledge assistant for one enterprise customer whose every step is visible: ask a question,
watch the agent search the governed knowledge base, get an answer with citations.
Built on lite-agent (the tool loop) and llm-steward (governed KB and memory, over HTTP).

Design: `docs/glassdesk-design.md`. Current plan: `docs/superpowers/plans/`.

```
cd backend && uv sync && cp .env.example .env   # fill it in
uv run glassdesk serve                         # http://127.0.0.1:8740
```
