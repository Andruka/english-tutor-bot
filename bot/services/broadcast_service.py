"""Controlled Telegram broadcast service with targeting and throttling."""

from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Literal

import aiosqlite
from aiogram import Bot

logger = logging.getLogger(__name__)

TargetKind = Literal["all", "level", "subscription", "user"]
SleepFn = Callable[[float], Awaitable[None] | None]


@dataclass(frozen=True)
class BroadcastTarget:
    """Target selector for a broadcast run."""

    kind: TargetKind
    value: str | None = None


@dataclass(frozen=True)
class BroadcastResult:
    """Delivery summary for a broadcast run."""

    total: int
    sent: int
    failed: int
    failures: list[tuple[int, str]] = field(default_factory=list)


class BroadcastService:
    """Sends messages to selected users with bounded throughput.

    The service is intentionally small and testable: it receives the already
    configured aiogram Bot and DB connection, and all destructive sending only
    happens from send().
    """

    def __init__(
        self,
        bot: Bot,
        conn: aiosqlite.Connection,
        sleep: SleepFn = asyncio.sleep,
    ) -> None:
        self.bot = bot
        self.conn = conn
        self.sleep = sleep

    async def resolve_user_ids(self, target: BroadcastTarget) -> list[int]:
        """Return sorted user_ids matching target."""
        if target.kind == "all":
            cursor = await self.conn.execute(
                "SELECT user_id FROM users ORDER BY user_id"
            )
            rows = await cursor.fetchall()
            return [int(row[0]) for row in rows]

        if target.kind == "level":
            level = (target.value or "").upper()
            cursor = await self.conn.execute(
                "SELECT user_id FROM users WHERE UPPER(level) = ? ORDER BY user_id",
                (level,),
            )
            rows = await cursor.fetchall()
            return [int(row[0]) for row in rows]

        if target.kind == "subscription":
            wanted = _parse_bool(target.value)
            cursor = await self.conn.execute(
                "SELECT user_id FROM users WHERE subscription = ? ORDER BY user_id",
                (1 if wanted else 0,),
            )
            rows = await cursor.fetchall()
            return [int(row[0]) for row in rows]

        if target.kind == "user":
            user_ids = _parse_user_ids(target.value or "")
            if not user_ids:
                return []
            placeholders = ",".join("?" for _ in user_ids)
            cursor = await self.conn.execute(
                f"SELECT user_id FROM users WHERE user_id IN ({placeholders}) ORDER BY user_id",
                tuple(user_ids),
            )
            rows = await cursor.fetchall()
            return [int(row[0]) for row in rows]

        raise ValueError(f"Unsupported broadcast target kind: {target.kind}")

    async def send(
        self,
        target: BroadcastTarget,
        text: str,
        messages_per_second: float = 1.0,
    ) -> BroadcastResult:
        """Send text to target users and throttle between attempts."""
        if not text.strip():
            raise ValueError("Broadcast text must not be empty")
        if messages_per_second <= 0:
            raise ValueError("messages_per_second must be positive")

        user_ids = await self.resolve_user_ids(target)
        delay = 1.0 / messages_per_second
        sent = 0
        failures: list[tuple[int, str]] = []

        for index, user_id in enumerate(user_ids):
            try:
                await self.bot.send_message(chat_id=user_id, text=text)
                sent += 1
            except Exception as exc:  # pragma: no cover - exact aiogram errors vary
                logger.warning("Broadcast delivery to %s failed: %s", user_id, exc)
                failures.append((user_id, str(exc)))

            if index < len(user_ids) - 1:
                maybe_awaitable = self.sleep(delay)
                if inspect.isawaitable(maybe_awaitable):
                    await maybe_awaitable

        return BroadcastResult(
            total=len(user_ids),
            sent=sent,
            failed=len(failures),
            failures=failures,
        )


def parse_broadcast_target(raw: str) -> BroadcastTarget:
    """Parse command target tokens: all, level:A1, subscription:true, user:1,2."""
    token = raw.strip()
    lowered = token.lower()
    if lowered == "all":
        return BroadcastTarget(kind="all")
    if lowered.startswith("level:"):
        value = token.split(":", 1)[1].strip().upper()
        if not value:
            raise ValueError("level target requires value, e.g. level:A1")
        return BroadcastTarget(kind="level", value=value)
    if lowered.startswith("subscription:"):
        value = token.split(":", 1)[1].strip().lower()
        _parse_bool(value)  # validate early
        return BroadcastTarget(kind="subscription", value=value)
    if lowered.startswith("user:"):
        value = token.split(":", 1)[1].strip()
        if not _parse_user_ids(value):
            raise ValueError("user target requires one or more numeric ids")
        return BroadcastTarget(kind="user", value=value)
    raise ValueError(
        "target must be all, level:<A1-C1>, subscription:<true|false>, or user:<id[,id]>"
    )


def _parse_user_ids(raw: str) -> list[int]:
    ids: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        ids.append(int(part))
    return sorted(set(ids))


def _parse_bool(raw: str | None) -> bool:
    value = (raw or "").strip().lower()
    if value in {"1", "true", "yes", "on", "paid", "active"}:
        return True
    if value in {"0", "false", "no", "off", "free", "inactive"}:
        return False
    raise ValueError("subscription target value must be true/false")
