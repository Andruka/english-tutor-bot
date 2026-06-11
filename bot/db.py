"""База данных AI-репетитора английского."""

import aiosqlite
import contextlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional


@dataclass
class User:
    user_id: int
    level: str  # A1-C2
    username: str
    dialogues_today: int = 0
    last_dialogue_date: Optional[date] = None
    subscription: bool = False
    subscription_expiry: Optional[str] = None  # ISO datetime
    streak: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class DialogueEntry:
    dialogue_id: int = 0
    user_id: int = 0
    topic: str = ""
    user_message: str = ""
    ai_reply: str = ""
    rating: int = 0
    corrections: list = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


_db_path: str = "english_tutor.db"
_open_connections: set[aiosqlite.Connection] = set()


async def init_db(db_path: str = None):
    """Инициализация таблиц БД."""
    global _db_path
    if db_path:
        _db_path = db_path

    async with aiosqlite.connect(_db_path) as conn:
        cursor = await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                level TEXT NOT NULL DEFAULT 'A2',
                username TEXT DEFAULT '',
                dialogues_today INTEGER DEFAULT 0,
                last_dialogue_date TEXT,
                subscription INTEGER DEFAULT 0,
                subscription_expiry TEXT,
                streak INTEGER DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
        """)

        await cursor.execute("""
            CREATE TABLE IF NOT EXISTS dialogues (
                dialogue_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                topic TEXT DEFAULT '',
                user_message TEXT DEFAULT '',
                ai_reply TEXT DEFAULT '',
                rating INTEGER DEFAULT 0,
                corrections TEXT DEFAULT '[]',
                timestamp TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );
        """)

        await cursor.execute("""
            CREATE TABLE IF NOT EXISTS achievements (
                user_id INTEGER NOT NULL,
                achievement_id TEXT NOT NULL,
                earned_at TEXT NOT NULL,
                PRIMARY KEY (user_id, achievement_id),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );
        """)

        await cursor.execute("""
            CREATE TABLE IF NOT EXISTS reminder_settings (
                user_id INTEGER PRIMARY KEY,
                remind_time TEXT NOT NULL DEFAULT '10:00',
                timezone TEXT NOT NULL DEFAULT 'Europe/Moscow',
                enabled INTEGER NOT NULL DEFAULT 1,
                last_notification_date TEXT,
                digest_enabled INTEGER NOT NULL DEFAULT 1,
                digest_time TEXT NOT NULL DEFAULT '21:00',
                last_digest_date TEXT,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );
        """)

        # Идемпотентная миграция для БД, созданных до daily digest.
        cursor = await conn.execute("PRAGMA table_info(reminder_settings)")
        existing_columns = {row[1] for row in await cursor.fetchall()}
        digest_columns = {
            "digest_enabled": "INTEGER NOT NULL DEFAULT 1",
            "digest_time": "TEXT NOT NULL DEFAULT '21:00'",
            "last_digest_date": "TEXT",
        }
        for column_name, definition in digest_columns.items():
            if column_name not in existing_columns:
                await conn.execute(
                    f"ALTER TABLE reminder_settings ADD COLUMN {column_name} {definition}"
                )

        await cursor.execute("""
            CREATE TABLE IF NOT EXISTS dictionary (
                word_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                word TEXT NOT NULL,
                translation TEXT NOT NULL,
                context TEXT DEFAULT '',
                level TEXT DEFAULT 'new',
                next_review TEXT,
                interval_days INTEGER DEFAULT 1,
                repetitions INTEGER DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );
        """)

        await conn.commit()


async def get_conn() -> aiosqlite.Connection:
    conn = await aiosqlite.connect(_db_path)
    conn.row_factory = aiosqlite.Row
    _open_connections.add(conn)
    return conn


async def close_all_connections() -> None:
    """Закрывает все долгоживущие подключения, открытые через get_conn().

    aiosqlite.Connection.close() дожидается выполнения всех поставленных в
    очередь операций перед закрытием, поэтому shutdown не обрывает текущий
    запрос на середине.
    """
    for conn in list(_open_connections):
        with contextlib.suppress(Exception):
            await conn.close()
        _open_connections.discard(conn)


class UserRepository:
    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn

    async def create(self, user_id: int, level: str, username: str) -> User:
        now = datetime.now(timezone.utc)
        await self.conn.execute(
            """INSERT OR IGNORE INTO users (user_id, level, username, created_at)
               VALUES (?, ?, ?, ?)""",
            (user_id, level, username, now.isoformat()),
        )
        await self.conn.commit()
        return await self.get(user_id)

    async def get(self, user_id: int) -> Optional[User]:
        cursor = await self.conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return self._row_to_user(row)

    async def update_level(self, user_id: int, new_level: str) -> User:
        await self.conn.execute(
            "UPDATE users SET level = ? WHERE user_id = ?",
            (new_level, user_id),
        )
        await self.conn.commit()
        return await self.get(user_id)

    async def set_level(self, user_id: int, level: str) -> User:
        """Синоним для update_level."""
        return await self.update_level(user_id, level)

    async def increment_dialogues(self, user_id: int) -> User:
        today = date.today()
        user = await self.get(user_id)
        if user.last_dialogue_date == today:
            await self.conn.execute(
                "UPDATE users SET dialogues_today = dialogues_today + 1 WHERE user_id = ?",
                (user_id,),
            )
        else:
            await self.conn.execute(
                "UPDATE users SET dialogues_today = 1, last_dialogue_date = ? WHERE user_id = ?",
                (today.isoformat(), user_id),
            )
        await self.conn.commit()
        return await self.get(user_id)

    async def reset_daily_dialogues(self):
        """Сброс счётчика диалогов (вызывается в начале нового дня)."""
        await self.conn.execute("UPDATE users SET dialogues_today = 0")
        await self.conn.commit()

    async def set_subscription(
        self, user_id: int, active: bool, expiry: str | None = None
    ):
        """Установка подписки пользователю."""
        await self.conn.execute(
            "UPDATE users SET subscription = ?, subscription_expiry = ? WHERE user_id = ?",
            (1 if active else 0, expiry, user_id),
        )
        await self.conn.commit()

    async def update_streak(self, user_id: int):
        """Обновление streak — если последний диалог был вчера, увеличиваем."""
        today = date.today()
        user = await self.get(user_id)
        if user.last_dialogue_date:
            last = user.last_dialogue_date
            if isinstance(last, str):
                last = date.fromisoformat(last)
            delta = (today - last).days
            if delta == 1:
                await self.conn.execute(
                    "UPDATE users SET streak = streak + 1 WHERE user_id = ?",
                    (user_id,),
                )
            elif delta > 1:
                await self.conn.execute(
                    "UPDATE users SET streak = 1 WHERE user_id = ?",
                    (user_id,),
                )
        else:
            await self.conn.execute(
                "UPDATE users SET streak = 1 WHERE user_id = ?",
                (user_id,),
            )
        await self.conn.commit()

    def _row_to_user(self, row) -> User:
        return User(
            user_id=row["user_id"],
            level=row["level"],
            username=row["username"] or "",
            dialogues_today=row["dialogues_today"] or 0,
            last_dialogue_date=(
                date.fromisoformat(row["last_dialogue_date"])
                if row["last_dialogue_date"]
                else None
            ),
            subscription=bool(row["subscription"]),
            subscription_expiry=row["subscription_expiry"],
            streak=row["streak"] or 0,
            created_at=datetime.fromisoformat(row["created_at"]),
        )


class DialogueRepository:
    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn

    async def save(
        self,
        user_id: int,
        user_message: str,
        ai_reply: str,
        topic: str = "",
        rating: int = 0,
        corrections: list = None,
    ) -> int:
        cursor = await self.conn.execute(
            """INSERT INTO dialogues (user_id, topic, user_message, ai_reply, rating, corrections)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                user_id,
                topic,
                user_message,
                ai_reply,
                rating,
                json.dumps(corrections or []),
            ),
        )
        await self.conn.commit()
        return cursor.lastrowid

    async def get_history(self, user_id: int, limit: int = 10) -> list[DialogueEntry]:
        cursor = await self.conn.execute(
            "SELECT * FROM dialogues WHERE user_id = ? ORDER BY timestamp DESC, dialogue_id DESC LIMIT ?",
            (user_id, limit),
        )
        rows = await cursor.fetchall()
        return [self._row_to_entry(row) for row in rows]

    async def count(self, user_id: int) -> int:
        """Количество диалогов пользователя."""
        cursor = await self.conn.execute(
            "SELECT COUNT(*) FROM dialogues WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def count_corrections(self, user_id: int) -> int:
        """Суммарное количество исправлений в диалогах пользователя."""
        cursor = await self.conn.execute(
            "SELECT corrections FROM dialogues WHERE user_id = ?", (user_id,)
        )
        rows = await cursor.fetchall()
        total = 0
        for row in rows:
            try:
                corrs = json.loads(row[0] or "[]")
                total += len(corrs)
            except (json.JSONDecodeError, TypeError):
                pass
        return total

    def _row_to_entry(self, row) -> DialogueEntry:
        return DialogueEntry(
            dialogue_id=row["dialogue_id"],
            user_id=row["user_id"],
            topic=row["topic"] or "",
            user_message=row["user_message"] or "",
            ai_reply=row["ai_reply"] or "",
            rating=row["rating"] or 0,
            corrections=json.loads(row["corrections"] or "[]"),
            timestamp=datetime.fromisoformat(row["timestamp"]),
        )


@dataclass
class WordEntry:
    word_id: int = 0
    user_id: int = 0
    word: str = ""
    translation: str = ""
    context: str = ""
    level: str = "new"
    next_review: Optional[str] = None
    interval_days: int = 1
    repetitions: int = 0
    created_at: Optional[str] = None


class DictionaryRepository:
    """SRS-словарь: добавление, повторение, прогресс."""

    SM2_INTERVALS = [1, 3, 7, 14, 30]

    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn

    async def add_word(
        self, user_id: int, word: str, translation: str, context: str = ""
    ) -> WordEntry:
        """Добавляет слово в словарь (или пропускает, если уже есть)."""
        from datetime import datetime, timezone, timedelta

        now = datetime.now(timezone.utc)
        next_review = (now + timedelta(days=1)).isoformat()

        cursor = await self.conn.execute(
            """INSERT OR IGNORE INTO dictionary
               (user_id, word, translation, context, next_review)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, word.lower(), translation, context, next_review),
        )
        await self.conn.commit()
        return await self.get_word_by_id(cursor.lastrowid) if cursor.lastrowid else None

    async def get_word_by_id(self, word_id: int) -> Optional[WordEntry]:
        cursor = await self.conn.execute(
            "SELECT * FROM dictionary WHERE word_id = ?", (word_id,)
        )
        row = await cursor.fetchone()
        return self._row_to_word(row) if row else None

    async def get_by_word(self, user_id: int, word: str) -> Optional[WordEntry]:
        cursor = await self.conn.execute(
            "SELECT * FROM dictionary WHERE user_id = ? AND word = ?",
            (user_id, word.lower()),
        )
        row = await cursor.fetchone()
        return self._row_to_word(row) if row else None

    async def get_due_words(self, user_id: int, limit: int = 10) -> list[WordEntry]:
        """Возвращает слова, которые нужно повторить сегодня."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        cursor = await self.conn.execute(
            """SELECT * FROM dictionary
               WHERE user_id = ? AND (next_review IS NULL OR next_review <= ?)
               ORDER BY next_review ASC LIMIT ?""",
            (user_id, now, limit),
        )
        rows = await cursor.fetchall()
        return [self._row_to_word(row) for row in rows]

    async def get_all(self, user_id: int) -> list[WordEntry]:
        cursor = await self.conn.execute(
            "SELECT * FROM dictionary WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_word(row) for row in rows]

    async def count(self, user_id: int) -> int:
        cursor = await self.conn.execute(
            "SELECT COUNT(*) FROM dictionary WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def count_due(self, user_id: int) -> int:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        cursor = await self.conn.execute(
            """SELECT COUNT(*) FROM dictionary
               WHERE user_id = ? AND (next_review IS NULL OR next_review <= ?)""",
            (user_id, now),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def mark_reviewed(self, word_id: int, quality: int) -> WordEntry:
        """SM-2 review. quality: 0=forgot, 1=hard, 2=okay, 3=easy."""
        from datetime import datetime, timezone, timedelta

        entry = await self.get_word_by_id(word_id)
        if not entry:
            return None

        if quality >= 2:
            new_reps = entry.repetitions + 1
            idx = min(new_reps - 1, len(self.SM2_INTERVALS) - 1)
            new_interval = self.SM2_INTERVALS[idx]
            new_level = "mastered" if new_interval >= 30 else "reviewing"
        else:
            new_reps = 0
            new_interval = 1
            new_level = "learning"

        next_review = (
            datetime.now(timezone.utc) + timedelta(days=new_interval)
        ).isoformat()

        await self.conn.execute(
            """UPDATE dictionary
               SET level = ?, next_review = ?, interval_days = ?, repetitions = ?
               WHERE word_id = ?""",
            (new_level, next_review, new_interval, new_reps, word_id),
        )
        await self.conn.commit()
        return await self.get_word_by_id(word_id)

    async def remove_word(self, word_id: int) -> bool:
        cursor = await self.conn.execute(
            "DELETE FROM dictionary WHERE word_id = ?", (word_id,)
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    def _row_to_word(self, row) -> WordEntry:
        return WordEntry(
            word_id=row["word_id"],
            user_id=row["user_id"],
            word=row["word"],
            translation=row["translation"],
            context=row["context"] or "",
            level=row["level"],
            next_review=row["next_review"],
            interval_days=row["interval_days"] or 1,
            repetitions=row["repetitions"] or 0,
            created_at=row["created_at"],
        )


@dataclass
class ReminderSettings:
    user_id: int
    remind_time: str = "10:00"  # HH:MM
    timezone: str = "Europe/Moscow"
    enabled: bool = True
    last_notification_date: Optional[str] = None
    digest_enabled: bool = True
    digest_time: str = "21:00"
    last_digest_date: Optional[str] = None


class ReminderSettingsRepository:
    """Repository для настроек ежедневных напоминаний."""

    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn

    async def get(self, user_id: int) -> Optional[ReminderSettings]:
        cursor = await self.conn.execute(
            "SELECT * FROM reminder_settings WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        return self._row_to_settings(row) if row else None

    async def upsert(self, settings: ReminderSettings) -> ReminderSettings:
        await self.conn.execute(
            """INSERT OR REPLACE INTO reminder_settings
               (user_id, remind_time, timezone, enabled, last_notification_date,
                digest_enabled, digest_time, last_digest_date)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                settings.user_id,
                settings.remind_time,
                settings.timezone,
                1 if settings.enabled else 0,
                settings.last_notification_date,
                1 if settings.digest_enabled else 0,
                settings.digest_time,
                settings.last_digest_date,
            ),
        )
        await self.conn.commit()
        return await self.get(settings.user_id)

    async def set_enabled(self, user_id: int, enabled: bool) -> None:
        await self.conn.execute(
            "UPDATE reminder_settings SET enabled = ? WHERE user_id = ?",
            (1 if enabled else 0, user_id),
        )
        await self.conn.commit()

    async def set_digest_enabled(self, user_id: int, enabled: bool) -> None:
        await self.conn.execute(
            "UPDATE reminder_settings SET digest_enabled = ? WHERE user_id = ?",
            (1 if enabled else 0, user_id),
        )
        await self.conn.commit()

    async def set_time(self, user_id: int, remind_time: str) -> None:
        await self.conn.execute(
            "UPDATE reminder_settings SET remind_time = ? WHERE user_id = ?",
            (remind_time, user_id),
        )
        await self.conn.commit()

    async def set_digest_time(self, user_id: int, digest_time: str) -> None:
        await self.conn.execute(
            "UPDATE reminder_settings SET digest_time = ? WHERE user_id = ?",
            (digest_time, user_id),
        )
        await self.conn.commit()

    async def set_last_notification(self, user_id: int, date_str: str) -> None:
        await self.conn.execute(
            "UPDATE reminder_settings SET last_notification_date = ? WHERE user_id = ?",
            (date_str, user_id),
        )
        await self.conn.commit()

    async def set_last_digest(self, user_id: int, date_str: str) -> None:
        await self.conn.execute(
            "UPDATE reminder_settings SET last_digest_date = ? WHERE user_id = ?",
            (date_str, user_id),
        )
        await self.conn.commit()

    async def set_last_digest_date(self, user_id: int, date_str: str) -> None:
        """Backward-compatible alias for set_last_digest."""
        await self.set_last_digest(user_id, date_str)

    async def get_all_enabled(self, time_hhmm: str) -> list[ReminderSettings]:
        """Возвращает всех пользователей с включёнными напоминаниями на данное время."""
        cursor = await self.conn.execute(
            "SELECT * FROM reminder_settings WHERE enabled = 1 AND remind_time = ?",
            (time_hhmm,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_settings(row) for row in rows]

    async def get_all_digest_enabled(
        self, time_hhmm: str | None = None
    ) -> list[ReminderSettings]:
        """Возвращает пользователей с включённым дайджестом.

        Если time_hhmm задан, дополнительно фильтрует по digest_time.
        """
        if time_hhmm is None:
            cursor = await self.conn.execute(
                "SELECT * FROM reminder_settings WHERE digest_enabled = 1"
            )
        else:
            cursor = await self.conn.execute(
                "SELECT * FROM reminder_settings WHERE digest_enabled = 1 AND digest_time = ?",
                (time_hhmm,),
            )
        rows = await cursor.fetchall()
        return [self._row_to_settings(row) for row in rows]

    async def ensure_user(self, user_id: int) -> ReminderSettings:
        """Создаёт запись с дефолтными настройками, если её нет."""
        existing = await self.get(user_id)
        if existing:
            return existing
        return await self.upsert(ReminderSettings(user_id=user_id))

    def _row_to_settings(self, row) -> Optional[ReminderSettings]:
        if not row:
            return None
        return ReminderSettings(
            user_id=row["user_id"],
            remind_time=row["remind_time"],
            timezone=row["timezone"],
            enabled=bool(row["enabled"]),
            last_notification_date=row["last_notification_date"],
            digest_enabled=bool(row["digest_enabled"]),
            digest_time=row["digest_time"] or "21:00",
            last_digest_date=row["last_digest_date"],
        )
