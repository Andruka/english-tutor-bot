"""Learning path recommendations from dialogue history."""

from collections import Counter
from typing import Any

from bot.db import DialogueRepository, UserRepository


_CATEGORY_TOPICS = {
    "article": ("Articles", "Articles (a/an/the)"),
    "tense": ("Tenses", "Past Simple vs Present Perfect"),
    "past": ("Tenses", "Past Simple vs Present Perfect"),
    "present perfect": ("Tenses", "Past Simple vs Present Perfect"),
    "preposition": ("Prepositions", "Prepositions of time and place"),
    "vocab": ("Vocabulary", "Vocabulary expansion"),
    "vocabulary": ("Vocabulary", "Vocabulary expansion"),
    "spelling": ("Spelling", "Spelling accuracy"),
    "grammar": ("Grammar", "Core grammar review"),
}

_AREA_REASON_LABELS = {
    "Articles": "артикли",
    "Tenses": "времена",
    "Prepositions": "предлоги",
    "Vocabulary": "словарный запас",
    "Spelling": "орфография",
    "Grammar": "грамматика",
}


def _classify_correction(
    category: str, original: str = "", corrected: str = ""
) -> tuple[str, str]:
    """Map raw AI correction data to a learning area and next lesson topic."""
    haystack = f"{category} {original} {corrected}".lower()
    for marker, learning_area in _CATEGORY_TOPICS.items():
        if marker in haystack:
            return learning_area
    return "Grammar", "Core grammar review"


def _plural_errors(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return f"{count} ошибка"
    if count % 10 in {2, 3, 4} and count % 100 not in {12, 13, 14}:
        return f"{count} ошибки"
    return f"{count} ошибок"


async def build_learning_path(
    user_id: int,
    conn,
    history_limit: int = 20,
) -> dict[str, Any]:
    """Build a deterministic personal next-lesson recommendation.

    Uses recent correction categories first. If there are no corrections yet,
    falls back to a diagnostic free-talk lesson calibrated by user level.
    """
    user = await UserRepository(conn).get(user_id)
    if user is None:
        raise ValueError("User not found")

    history = await DialogueRepository(conn).get_history(user_id, limit=history_limit)
    weak_area_counts: Counter[tuple[str, str]] = Counter()
    topic_counts: Counter[str] = Counter()
    low_rating_topics: Counter[str] = Counter()

    for entry in history:
        if entry.topic:
            topic_counts[entry.topic] += 1
        if entry.rating and entry.rating <= 3 and entry.topic:
            low_rating_topics[entry.topic] += 1
        for correction in entry.corrections:
            weak_area_counts[
                _classify_correction(
                    str(correction.get("category", "")),
                    str(correction.get("original", "")),
                    str(correction.get("corrected", "")),
                )
            ] += 1

    weak_areas = [
        {"name": name, "recommended_topic": topic, "count": count}
        for (name, topic), count in weak_area_counts.most_common(3)
    ]

    if weak_areas:
        top = weak_areas[0]
        error_text = _plural_errors(top["count"])
        area_label = _AREA_REASON_LABELS.get(top["name"], top["name"])
        return {
            "recommended_topic": top["recommended_topic"],
            "reason": f"Нашёл {error_text} в зоне «{area_label}» за последние {len(history)} диалогов.",
            "weak_areas": weak_areas,
            "recent_topics": topic_counts.most_common(5),
            "next_prompt": _build_next_prompt(top["recommended_topic"]),
        }

    if low_rating_topics:
        topic, count = low_rating_topics.most_common(1)[0]
        return {
            "recommended_topic": topic.replace("_", " ").title(),
            "reason": f"В теме «{topic}» были низкие оценки ({count}), поэтому стоит закрепить её ещё раз.",
            "weak_areas": [],
            "recent_topics": topic_counts.most_common(5),
            "next_prompt": f"Tell me about {topic.replace('_', ' ')} in 5–7 sentences.",
        }

    return {
        "recommended_topic": "Free Talk diagnostic",
        "reason": f"Пока нет истории ошибок — начнём с короткой диагностики уровня {user.level}.",
        "weak_areas": [],
        "recent_topics": topic_counts.most_common(5),
        "next_prompt": "Tell me about your day, your work, and one thing you want to improve in English.",
    }


def _build_next_prompt(topic: str) -> str:
    prompts = {
        "Articles (a/an/the)": "Write 5 sentences about your home or work using a/an/the.",
        "Past Simple vs Present Perfect": "Tell me what you did yesterday and what you have already done today.",
        "Prepositions of time and place": "Describe your daily schedule and where things are in your room.",
        "Vocabulary expansion": "Describe your favourite topic and ask for 5 new useful words.",
        "Spelling accuracy": "Write a short paragraph slowly and carefully; I will check spelling.",
        "Core grammar review": "Write 5–7 sentences about a familiar topic; I will find the main grammar pattern to practice.",
    }
    return prompts.get(
        topic, "Write 5–7 sentences on this topic so I can guide the next step."
    )


def format_learning_path(recommendation: dict[str, Any]) -> str:
    """Render a learning path recommendation for Telegram."""
    text = (
        "🎯 <b>Learning Path</b>\n\n"
        f"Следующий урок: <b>{recommendation['recommended_topic']}</b>\n"
        f"Почему: {recommendation['reason']}\n"
    )

    if recommendation.get("weak_areas"):
        text += "\nСлабые зоны:\n"
        for area in recommendation["weak_areas"]:
            text += f"• {area['name']}: {_plural_errors(area['count'])}\n"

    if recommendation.get("next_prompt"):
        text += f"\nСтартовое задание:\n<i>{recommendation['next_prompt']}</i>"

    text += (
        "\n\nСовет: включи /mode → 📚 Грамматика, если хочешь отработать тему точечно."
    )
    return text
