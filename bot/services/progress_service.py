"""Progress Service — достижения, streak, дашборд прогресса."""

import logging
from datetime import date

logger = logging.getLogger(__name__)

SKILL_BRANCHES = {
    "vocabulary": {
        "name": "Vocabulary",
        "icon": "📚",
        "desc": "Слова и устойчивые выражения",
    },
    "grammar": {"name": "Grammar", "icon": "🧩", "desc": "Грамматика и точность"},
    "speaking": {"name": "Speaking", "icon": "🗣", "desc": "Беглость и диалоги"},
    "listening": {"name": "Listening", "icon": "🎧", "desc": "Аудирование и голос"},
    "writing": {"name": "Writing", "icon": "✍️", "desc": "Письменные ответы"},
}
POINTS_PER_LEVEL = 100
RANK_THRESHOLDS = [
    (900, "Platinum"),
    (600, "Gold"),
    (300, "Silver"),
    (0, "Bronze"),
]

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
    "weekly_challenge": {
        "name": "🎯 Weekly Challenge",
        "desc": "Выполни недельный челлендж: 7 практик за неделю",
    },
    "skill_tree_started": {
        "name": "🌱 Первые очки навыков",
        "desc": "Получи первые очки в дереве навыков",
    },
}


def _branch_row(branch_id: str, points: int) -> dict:
    branch = SKILL_BRANCHES[branch_id]
    return {
        "id": branch_id,
        "branch_id": branch_id,
        "name": branch["name"],
        "icon": branch["icon"],
        "desc": branch["desc"],
        "points": points,
        "level": points // POINTS_PER_LEVEL,
        "points_to_next_level": POINTS_PER_LEVEL - (points % POINTS_PER_LEVEL),
    }


def _current_week_id() -> str:
    year, week, _weekday = date.today().isocalendar()
    return f"{year}-W{week:02d}"


def calculate_rank(skill_tree: list[dict]) -> str:
    """Ранг пользователя по сумме очков дерева навыков."""
    total_points = sum(branch.get("points", 0) for branch in skill_tree)
    for threshold, rank in RANK_THRESHOLDS:
        if total_points >= threshold:
            return rank
    return "Bronze"


class SkillProgressRepository:
    """Repository для дерева навыков пользователя."""

    def __init__(self, conn):
        self.conn = conn

    async def get_branch(self, user_id: int, branch_id: str) -> dict:
        if branch_id not in SKILL_BRANCHES:
            raise ValueError(f"Unknown skill branch: {branch_id}")
        cursor = await self.conn.execute(
            "SELECT points FROM skill_progress WHERE user_id = ? AND branch_id = ?",
            (user_id, branch_id),
        )
        row = await cursor.fetchone()
        return _branch_row(branch_id, row[0] if row else 0)

    async def get_tree(self, user_id: int) -> list[dict]:
        return [
            await self.get_branch(user_id, branch_id) for branch_id in SKILL_BRANCHES
        ]

    async def award_points(self, user_id: int, branch_id: str, points: int) -> dict:
        if branch_id not in SKILL_BRANCHES:
            raise ValueError(f"Unknown skill branch: {branch_id}")
        if points <= 0:
            return await self.get_branch(user_id, branch_id)
        await self.conn.execute(
            """INSERT INTO skill_progress (user_id, branch_id, points, updated_at)
               VALUES (?, ?, ?, datetime('now'))
               ON CONFLICT(user_id, branch_id)
               DO UPDATE SET points = points + excluded.points, updated_at = datetime('now')""",
            (user_id, branch_id, points),
        )
        await self.conn.commit()
        return await self.get_branch(user_id, branch_id)


async def get_skill_tree(
    user_id: int, repo: SkillProgressRepository | None = None
) -> list[dict]:
    """Возвращает пять веток дерева навыков с очками и уровнями."""
    if repo is None:
        from bot.db import get_conn

        conn = await get_conn()
        repo = SkillProgressRepository(conn)
    return await repo.get_tree(user_id)


class WeeklyChallengeRepository:
    """Repository для еженедельного челленджа."""

    def __init__(self, conn):
        self.conn = conn

    async def get_or_create_current(self, user_id: int) -> dict:
        week_id = _current_week_id()
        await self.conn.execute(
            """INSERT OR IGNORE INTO weekly_challenges
               (user_id, week_id, goal, progress, completed, reward_achievement_id)
               VALUES (?, ?, 7, 0, 0, 'weekly_challenge')""",
            (user_id, week_id),
        )
        await self.conn.commit()
        return await self._get(user_id, week_id)

    async def increment_progress(self, user_id: int, amount: int = 1) -> dict:
        challenge = await self.get_or_create_current(user_id)
        if challenge["completed"]:
            return challenge
        new_progress = min(challenge["goal"], challenge["progress"] + amount)
        completed = new_progress >= challenge["goal"]
        await self.conn.execute(
            """UPDATE weekly_challenges
               SET progress = ?, completed = ?, updated_at = datetime('now')
               WHERE user_id = ? AND week_id = ?""",
            (new_progress, 1 if completed else 0, user_id, challenge["week_id"]),
        )
        await self.conn.commit()
        updated = await self._get(user_id, challenge["week_id"])
        if completed:
            await AchievementRepository(self.conn).add(
                user_id, updated["reward_achievement_id"]
            )
        return updated

    async def _get(self, user_id: int, week_id: str) -> dict:
        cursor = await self.conn.execute(
            """SELECT user_id, week_id, goal, progress, completed, reward_achievement_id
               FROM weekly_challenges WHERE user_id = ? AND week_id = ?""",
            (user_id, week_id),
        )
        row = await cursor.fetchone()
        return {
            "user_id": row[0],
            "week_id": row[1],
            "goal": row[2],
            "progress": row[3],
            "completed": bool(row[4]),
            "reward_achievement_id": row[5],
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
    skill_repo = SkillProgressRepository(conn)
    challenge_repo = WeeklyChallengeRepository(conn)

    user = await user_repo.get(user_id)
    if user is None:
        return {"error": "User not found"}

    total = await dial_repo.count(user_id)
    achievements = await ach_repo.get_all(user_id)
    ach_count = len(achievements)
    skill_tree = await skill_repo.get_tree(user_id)
    weekly_challenge = await challenge_repo.get_or_create_current(user_id)

    return {
        "level": user.level,
        "streak": user.streak,
        "dialogues_today": user.dialogues_today,
        "total_dialogues": total,
        "subscription": bool(user.subscription),
        "achievement_count": ach_count,
        "achievements": achievements,
        "skill_tree": skill_tree,
        "rank": calculate_rank(skill_tree),
        "weekly_challenge": weekly_challenge,
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
