"""Progress Service — достижения, streak, дашборд прогресса."""

import logging
from datetime import date

logger = logging.getLogger(__name__)

ACHIEVEMENT_DEFINITIONS = {
    "first_lesson": {
        "name": "🎓 Первый урок",
        "desc": "Заверши первый диалог с репетитором",
    },
    "streak_7": {"name": "🔥 Неделя практики", "desc": "Занимайся 7 дней подряд"},
    "streak_14": {"name": "⚡ Две недели", "desc": "Занимайся 14 дней подряд"},
    "streak_30": {"name": "💪 Месяц практики", "desc": "Занимайся 30 дней подряд"},
    "dialogues_50": {
        "name": "💬 50 диалогов",
        "desc": "Проведи 50 диалогов с репетитором",
    },
    "dialogues_100": {
        "name": "🎯 100 диалогов",
        "desc": "Проведи 100 диалогов с репетитором",
    },
    "dialogues_500": {
        "name": "🏆 500 диалогов",
        "desc": "Проведи 500 диалогов с репетитором",
    },
    "first_correction": {
        "name": "📝 Первое исправление",
        "desc": "Получи первое исправление ошибки от AI",
    },
    "all_corrections_accepted": {
        "name": "🌟 Ученик",
        "desc": "Получи 10 исправлений от AI",
    },
}


class AchievementRepository:
    """Repository для таблицы достижений."""

    def __init__(self, conn):
        self.conn = conn

    async def add(self, user_id: int, achievement_id: str) -> bool:
        """Добавляет достижение. Возвращает True, если добавлено новое."""
        try:
            cursor = await self.conn.execute(
                "INSERT OR IGNORE INTO achievements (user_id, achievement_id, earned_at) VALUES (?, ?, ?)",
                (user_id, achievement_id, date.today().isoformat()),
            )
            await self.conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(
                f"Failed to add achievement {achievement_id} for user {user_id}: {e}"
            )
            return False

    async def has(self, user_id: int, achievement_id: str) -> bool:
        """Проверяет, есть ли достижение у пользователя."""
        cursor = await self.conn.execute(
            "SELECT 1 FROM achievements WHERE user_id = ? AND achievement_id = ?",
            (user_id, achievement_id),
        )
        row = await cursor.fetchone()
        return row is not None

    async def get_all(self, user_id: int) -> list[dict]:
        """Возвращает все достижения пользователя."""
        cursor = await self.conn.execute(
            "SELECT achievement_id, earned_at FROM achievements WHERE user_id = ? ORDER BY earned_at",
            (user_id,),
        )
        rows = await cursor.fetchall()
        return [
            {
                "achievement_id": row[0],
                "name": ACHIEVEMENT_DEFINITIONS.get(row[0], {}).get("name", row[0]),
                "desc": ACHIEVEMENT_DEFINITIONS.get(row[0], {}).get("desc", ""),
                "earned_at": row[1],
            }
            for row in rows
        ]

    async def count(self, user_id: int) -> int:
        """Считает количество достижений пользователя."""
        cursor = await self.conn.execute(
            "SELECT COUNT(*) FROM achievements WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0


class AchievementChecker:
    """Проверяет и выдаёт новые достижения после каждого диалога."""

    def __init__(self, conn):
        self.conn = conn
        self.ach_repo = AchievementRepository(conn)

    async def check_after_dialogue(
        self,
        user_id: int,
        dialogue_count: int,
        streak: int,
        corrections: list[dict],
    ) -> list[str]:
        """Проверяет условия и возвращает список новых достижений."""
        new_achievements = []

        checks = [
            ("first_lesson", dialogue_count >= 1),
            ("dialogues_50", dialogue_count >= 50),
            ("dialogues_100", dialogue_count >= 100),
            ("dialogues_500", dialogue_count >= 500),
            ("streak_7", streak >= 7),
            ("streak_14", streak >= 14),
            ("streak_30", streak >= 30),
        ]

        # Проверка первого исправления
        if corrections:
            # Считаем общее количество исправлений через DialogueRepository
            total_corrections = await self._count_corrections(user_id, corrections)
            if total_corrections >= 1:
                checks.append(
                    (
                        "first_correction",
                        not await self.ach_repo.has(user_id, "first_correction"),
                    )
                )
            if total_corrections >= 10:
                checks.append(
                    (
                        "all_corrections_accepted",
                        not await self.ach_repo.has(
                            user_id, "all_corrections_accepted"
                        ),
                    )
                )

        for ach_id, condition in checks:
            if condition and not await self.ach_repo.has(user_id, ach_id):
                added = await self.ach_repo.add(user_id, ach_id)
                if added:
                    new_achievements.append(ach_id)

        return new_achievements

    async def _count_corrections(self, user_id: int, current_corrections: list) -> int:
        """Считает общее количество исправлений пользователя."""
        # Считаем исправления в последнем диалоге + в БД (если хранятся)
        from bot.db import DialogueRepository

        dial_repo = DialogueRepository(self.conn)
        total = len(current_corrections)
        # Если в БД хранятся исправления — добавляем
        try:
            stored = await dial_repo.count_corrections(user_id)
            total += stored
        except Exception:
            pass
        return total


async def get_progress_dashboard(user_id: int) -> dict:
    """Формирует дашборд прогресса пользователя."""
    from bot.db import get_conn, UserRepository, DialogueRepository

    conn = await get_conn()
    user_repo = UserRepository(conn)
    dial_repo = DialogueRepository(conn)
    ach_repo = AchievementRepository(conn)

    user = await user_repo.get(user_id)
    if user is None:
        return {"error": "User not found"}

    total = await dial_repo.count(user_id)
    achievements = await ach_repo.get_all(user_id)
    ach_count = len(achievements)

    return {
        "level": user.level,
        "streak": user.streak,
        "dialogues_today": user.dialogues_today,
        "total_dialogues": total,
        "subscription": bool(user.subscription),
        "achievement_count": ach_count,
        "achievements": achievements,
    }


def format_achievements_text(achievements: list[dict]) -> str:
    """Форматирует список достижений в красивый текст."""
    if not achievements:
        return "Пока нет достижений. Начни заниматься, чтобы получить первые! 🚀"

    lines = []
    for a in achievements:
        _emoji = a.get("achievement_id", "")[:2]
        lines.append(f"  {a['name']} — {a['desc']}")
    return "\n".join(lines)
