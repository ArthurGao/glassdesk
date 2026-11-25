"""The `glassdesk` command line."""

import argparse
import json
from collections.abc import Sequence

from glassdesk.config import Settings


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="glassdesk")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="run the API (and the built SPA when static_dir is set)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8740)
    sub.add_parser("openapi", help="print the OpenAPI document as JSON")
    args = parser.parse_args(argv)

    if args.command == "serve":
        import uvicorn

        from glassdesk.app import create_app

        uvicorn.run(create_app(Settings()), host=args.host, port=args.port)
    elif args.command == "openapi":
        print(json.dumps(_openapi(), indent=2, ensure_ascii=False))
    return 0


def _openapi() -> dict[str, object]:
    from glassdesk.app import create_app

    # The schema does not depend on settings values: placeholders keep this runnable without .env.
    placeholder = Settings(
        database_url="postgresql+psycopg://openapi@localhost/openapi",
        steward_api_key="unused",
        session_secret="o" * 32,
        _env_file=None,
    )
    return create_app(placeholder).openapi()


if __name__ == "__main__":
    raise SystemExit(main())
