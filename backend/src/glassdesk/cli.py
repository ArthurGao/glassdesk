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
    serve.add_argument(
        "--fake",
        action="store_true",
        help="a scripted model and a fixed demo knowledge base (demos without a model, e2e)",
    )
    serve.add_argument(
        "--proxy-headers",
        action="store_true",
        help="behind a TLS-terminating proxy: trust X-Forwarded-* (secure cookies, client IP)",
    )
    sub.add_parser("openapi", help="print the OpenAPI document as JSON")
    sub.add_parser("migrate", help="create or upgrade the app's and lite-agent's tables")
    sub.add_parser("setup", help="create the deployment's steward collection if missing")
    seed = sub.add_parser("seed", help="write demo knowledge to steward")
    seed.add_argument("--demo", action="store_true", required=True, help="the fictional company")
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

        settings = Settings()
        deps = _fake_deps(settings) if args.fake else None
        uvicorn.run(
            create_app(settings, deps=deps),
            host=args.host,
            port=args.port,
            proxy_headers=args.proxy_headers,
            forwarded_allow_ips="*" if args.proxy_headers else None,
        )
        return 0
    if args.command == "openapi":
        print(json.dumps(_openapi(), indent=2, ensure_ascii=False))
        return 0
    return asyncio.run(run(args))


async def run(args: argparse.Namespace | Sequence[str], *, deps: Deps | None = None) -> int:
    """The commands that touch the database; `deps` lets tests point them at their schema."""
    if not isinstance(args, argparse.Namespace):
        args = _parser().parse_args(args)
    if args.command == "migrate":
        from glassdesk.db import run_migrations

        settings = Settings()
        await run_migrations(settings.database_url, settings.db_schema, settings.agent_schema)
        print("migrated")
        return 0
    if args.command == "seed":
        from glassdesk.seed import seed_demo
        from glassdesk.steward import HttpSteward

        steward = HttpSteward.from_settings(Settings())
        try:
            print(f"demo entries written: {await seed_demo(steward)}")
        finally:
            await steward.aclose()
        return 0
    if args.command == "setup":
        from glassdesk.steward import HttpSteward

        settings = Settings()
        steward = HttpSteward.from_settings(settings)
        try:
            print(f"collection {settings.steward_collection}: {await steward.ensure_collection()}")
        finally:
            await steward.aclose()
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
            from glassdesk.app import close_deps

            await close_deps(deps)


def _fake_deps(settings: Settings) -> Deps:
    from dataclasses import replace

    from glassdesk.app import build_deps
    from glassdesk.fakes import DEMO_PASSAGES, demo_model
    from glassdesk.testing import FakeSteward

    real = build_deps(settings.model_copy(update={"llm": None}))
    return replace(real, model=demo_model(), steward=FakeSteward(DEMO_PASSAGES))


def _openapi() -> dict[str, object]:
    from glassdesk.app import create_app

    # The schema does not depend on settings values: placeholders keep this runnable without .env.
    placeholder = Settings(
        database_url="postgresql+psycopg://openapi@localhost/openapi",
        steward_api_key="unused",
        steward_review_key="unused",
        session_secret="o" * 32,
        _env_file=None,
    )
    return create_app(placeholder).openapi()


if __name__ == "__main__":
    raise SystemExit(main())
