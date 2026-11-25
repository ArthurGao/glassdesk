"""Local accounts: one deployment, one customer (design §7)."""

import uuid
from dataclasses import dataclass
from typing import Any, Literal, get_args

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    Table,
    Text,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.engine import Row
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

Role = Literal["member", "reviewer", "admin"]
ROLES: tuple[Role, ...] = get_args(Role)

metadata = MetaData()
users = Table(
    "users",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("username", Text, nullable=False),
    Column("password_hash", Text, nullable=False),
    Column("role", Text, nullable=False),
    Column("session_version", Integer, nullable=False, server_default="0"),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

_hasher = PasswordHasher()
# Verified against when the username is unknown, so both failures cost the same time.
_DUMMY_HASH = _hasher.hash("glassdesk-no-such-user")


@dataclass(frozen=True)
class User:
    id: uuid.UUID
    username: str
    role: Role
    session_version: int = 0


class DuplicateUser(Exception):
    pass


def _user(row: Row[Any]) -> User:
    return User(
        id=row.id, username=row.username, role=row.role, session_version=row.session_version
    )


async def create_user(engine: AsyncEngine, username: str, password: str, role: Role) -> User:
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    user = User(id=uuid.uuid4(), username=username, role=role)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                insert(users).values(
                    id=user.id, username=username, password_hash=_hasher.hash(password), role=role
                )
            )
    except IntegrityError as exc:
        raise DuplicateUser(username) from exc
    return user


async def authenticate(engine: AsyncEngine, username: str, password: str) -> User | None:
    async with engine.connect() as conn:
        row = (await conn.execute(select(users).where(users.c.username == username))).first()
    try:
        _hasher.verify(row.password_hash if row else _DUMMY_HASH, password)
    except VerificationError:
        return None
    return _user(row) if row else None


async def get_user(engine: AsyncEngine, user_id: uuid.UUID) -> User | None:
    async with engine.connect() as conn:
        row = (await conn.execute(select(users).where(users.c.id == user_id))).first()
    return _user(row) if row else None


async def end_sessions(engine: AsyncEngine, user_id: uuid.UUID) -> None:
    """Invalidate every session cookie issued to this user so far (logout, password change)."""
    async with engine.begin() as conn:
        await conn.execute(
            update(users)
            .where(users.c.id == user_id)
            .values(session_version=users.c.session_version + 1)
        )
