"""Pydantic модели для геймификации и прогресса."""

from datetime import date
from pydantic import BaseModel, Field


class SkillBranch(BaseModel):
    """Ветка дерева навыков."""

    id: str = ""
    name: str = ""
    icon: str = ""
    desc: str = ""
    points: int = 0
    level: int = 0
    points_to_next_level: int = 100


class WeeklyChallenge(BaseModel):
    """Еженедельный челлендж."""

    week_id: str = ""
    goal: int = 7
    progress: int = 0
    completed: bool = False
    reward_name: str = ""


class Achievement(BaseModel):
    """Достижение пользователя."""

    achievement_id: str = ""
    name: str = ""
    desc: str = ""
    earned_at: date | None = None


class ProgressDashboard(BaseModel):
    """Дашборд прогресса пользователя."""

    level: int = 1
    streak: int = 0
    dialogues_today: int = 0
    total_dialogues: int = 0
    subscription: bool = False
    achievement_count: int = 0
    achievements: list[Achievement] = Field(default_factory=list)
    skill_tree: list[SkillBranch] = Field(default_factory=list)
    rank: str = "Bronze"
    weekly_challenge: WeeklyChallenge | None = None
    dictionary_words: int = 0
    total_xp: int = 0
    xp_to_next_rank: int = 0
    next_rank_name: str = ""
