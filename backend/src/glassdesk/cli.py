"""The `glassdesk` command line."""

import argparse
import asyncio
import getpass
import json
import sys
from collections.abc import Sequence

from glassdesk.config import Settings
from glassdesk.db import Deps
from glassdesk.users import ROLES, DuplicateUser, create_user


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="glassdesk")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="run the API (and the built SPA when static_dir is set)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8740)
    sub.add_parser("openapi", help="print the OpenAPI document as JSON")
    sub.add_parser("migrate", help="create or upgrade the app's and lite-agent's tables")
    user = sub.add_parser("user", help="manage local accounts").add_subparsers(
        dest="action", required=True
    )
    create = user.add_parser("create", help="create an account")
    create.add_argument("username")
    create.add_argument("--role", choices=ROLES, default="member")
    create.add_argument(
        "--password-stdin", action="store_true", help="read the password from stdin"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "serve":
        import uvicorn

        from glassdesk.app import create_app

        uvicorn.run(create_app(Settings()), host=args.host, port=args.port)
        return 0
    if args.command == "openapi":
        print(json.dumps(_openapi(), indent=2, ensure_ascii=False))
        return 0
    return asyncio.run(run(argv))


async def run(argv: Sequence[str] | None, *, deps: Deps | None = None) -> int:
    """The commands that touch the database; `deps` lets tests point them at their schema."""
    args = _parser().parse_args(argv)
    if args.command == "migrate":
        from glassdesk.db import run_migrations

        settings = Settings()
        await run_migrations(settings.database_url, settings.db_schema, settings.agent_schema)
        print("migrated")
        return 0
    owned = deps is None
    if deps is None:
        from glassdesk.app import build_deps

        deps = build_deps(Settings())
    try:
        password = (
            sys.stdin.readline().rstrip("\n") if args.password_stdin else getpass.getpass("密码：")
        )
        if not password:
            print("password must not be empty", file=sys.stderr)
            return 2
        try:
            await create_user(deps.engine, args.username, password, args.role)
        except DuplicateUser:
            print(f"user {args.username!r} already exists", file=sys.stderr)
            return 1
        print(f"created {args.username} ({args.role})")
        return 0
    finally:
        if owned:
            await deps.engine.dispose()


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
