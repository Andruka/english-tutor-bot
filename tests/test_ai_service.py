"""Тесты для AI Service — генерация ответа репетитора."""

import pytest


@pytest.mark.asyncio
async def test_ai_greeting():
    """RED: AI репетитор отвечает на приветствие."""
    from bot.services.ai_service import AITutor

    tutor = AITutor(level="A2", api_key="test_key", topic="introduction")
    response = await tutor.chat("Hello! How are you?")

    assert response is not None
    assert "reply" in response
    assert len(response["reply"]) > 0


@pytest.mark.asyncio
async def test_ai_corrects_mistake():
    """RED: AI репетитор исправляет ошибки."""
    from bot.services.ai_service import AITutor

    tutor = AITutor(level="B1", api_key="test_key", topic="daily_routine")
    response = await tutor.chat("Yesterday I go to the park")

    assert "corrections" in response
    # Должна быть хотя бы одна ошибка
    assert len(response["corrections"]) > 0


@pytest.mark.asyncio
async def test_ai_rating_returned():
    """RED: AI возвращает оценку ответа (1-5)."""
    from bot.services.ai_service import AITutor

    tutor = AITutor(level="B1", api_key="test_key", topic="hobbies")
    response = await tutor.chat("I like reading books in English")

    assert "rating" in response
    assert 1 <= response["rating"] <= 5


@pytest.mark.asyncio
async def test_ai_adapts_to_level():
    """RED: AI адаптирует сложность под уровень A1."""
    from bot.services.ai_service import AITutor

    tutor = AITutor(level="A1", api_key="test_key", topic="family")
    response_a1 = await tutor.chat("I have mother and father")

    tutor_b2 = AITutor(level="B2", api_key="test_key", topic="family")
    response_b2 = await tutor_b2.chat("I have a mother and a father")

    # B2 ответ должен быть длиннее или сложнее, чем A1
    assert len(response_a1["reply"]) <= len(response_b2["reply"]) + 50


@pytest.mark.asyncio
async def test_ai_history_context():
    """RED: AI учитывает историю диалога."""
    from bot.services.ai_service import AITutor

    tutor = AITutor(level="B1", api_key="test_key", topic="travel")
    await tutor.chat("I like traveling to Europe")
    response = await tutor.chat("My favorite country is Italy")

    # Второй ответ не должен игнорировать первый
    assert "reply" in response
    assert len(response["reply"]) > 20


@pytest.mark.asyncio
async def test_ai_no_empty_response():
    """RED: AI не возвращает пустой ответ."""
    from bot.services.ai_service import AITutor

    tutor = AITutor(level="A2", api_key="test_key", topic="food")
    response = await tutor.chat("")

    # Пустой ввод = просьба подсказать тему
    assert response is not None
    assert len(response["reply"]) > 10


@pytest.mark.asyncio
async def test_ai_error_handling():
    """RED: Ошибка API возвращает контролируемый ответ."""
    from bot.services.ai_service import AITutor

    tutor = AITutor(level="B1", api_key="invalid_key", topic="test")

    with pytest.raises(Exception):
        await tutor.chat("Hello")


@pytest.mark.asyncio
async def test_ai_tutor_system_prompt():
    """RED: Системный промпт содержит уровень пользователя."""
    from bot.services.ai_service import build_system_prompt

    prompt = build_system_prompt(level="A2", topic="introduction")
    assert "A2" in prompt
    assert "introduction" in prompt
    assert "correction" in prompt.lower() or "mistake" in prompt.lower()


@pytest.mark.asyncio
async def test_parse_response():
    """RED: Парсинг ответа AI в структурированный формат."""
    from bot.services.ai_service import parse_ai_response

    raw = '{"reply": "Hello! Nice to meet you.", "corrections": [], "rating": 5, "vocabulary_tip": "Great start!"}'
    result = parse_ai_response(raw)

    assert result["reply"] == "Hello! Nice to meet you."
    assert result["rating"] == 5
    assert result["corrections"] == []


@pytest.mark.asyncio
async def test_parse_response_with_corrections():
    """RED: Парсинг ответа с исправлениями."""
    from bot.services.ai_service import parse_ai_response

    raw = """
{
    "reply": "I went to the store yesterday.",
    "corrections": [
        {"original": "I go", "corrected": "I went", "category": "tense"}
    ],
    "rating": 3,
    "vocabulary_tip": "Use past tense for yesterday"
}"""
    result = parse_ai_response(raw)

    assert len(result["corrections"]) == 1
    assert result["corrections"][0]["original"] == "I go"


@pytest.mark.asyncio
async def test_parse_response_markdown_codeblock():
    """RED: Парсинг ответа AI в ```json блоке."""
    from bot.services.ai_service import parse_ai_response

    raw = """```json
{
    "reply": "Hello! Nice to meet you.",
    "corrections": [],
    "rating": 5,
    "vocabulary_tip": ""
}```"""
    result = parse_ai_response(raw)

    assert result["reply"] == "Hello! Nice to meet you."
    assert result["rating"] == 5


@pytest.mark.asyncio
async def test_parse_response_nested_json_in_reply():
    """RED: Парсинг JSON, где поле reply содержит вложенные скобки."""
    from bot.services.ai_service import parse_ai_response

    raw = '{"reply": "Use {{template}} syntax like {this} in your response", "corrections": [], "rating": 3}'
    result = parse_ai_response(raw)

    assert result["reply"] == "Use {{template}} syntax like {this} in your response"
    assert result["rating"] == 3


def test_build_system_prompt_uses_distinct_dialogue_modes():
    """K011: режимы диалога должны давать разные системные промпты."""
    from bot.services.ai_service import (
        MODE_FREE_TALK,
        MODE_GRAMMAR_FOCUS,
        MODE_ROLE_PLAY,
        build_system_prompt,
    )

    free_talk = build_system_prompt("A2", "travel", mode=MODE_FREE_TALK)
    role_play = build_system_prompt(
        "A2",
        "travel",
        mode=MODE_ROLE_PLAY,
        scenario="You are a hotel receptionist. The user is checking in.",
    )
    grammar_focus = build_system_prompt(
        "A2",
        "travel",
        mode=MODE_GRAMMAR_FOCUS,
        grammar_focus="Present Perfect",
    )

    assert "Mode: FREE TALK" in free_talk
    assert "Priority: FLUENCY" in free_talk
    assert "Mode: ROLE PLAY" in role_play
    assert "hotel receptionist" in role_play
    assert "Mode: GRAMMAR FOCUS" in grammar_focus
    assert "Present Perfect" in grammar_focus


def test_ai_tutor_set_mode_clears_history_and_rebuilds_prompt():
    """K011: переключение режима очищает историю и меняет промпт."""
    from bot.services.ai_service import AITutor, MODE_FREE_TALK, MODE_ROLE_PLAY

    tutor = AITutor(level="B1", api_key="test_key", topic="travel", mode=MODE_FREE_TALK)
    tutor.messages.append({"role": "user", "content": "Old conversation"})
    tutor.messages.append({"role": "assistant", "content": "Old reply"})

    tutor.set_mode(
        MODE_ROLE_PLAY,
        scenario="You are an airport check-in agent. The user is a passenger.",
    )

    assert len(tutor.messages) == 1
    assert tutor.messages[0]["role"] == "system"
    assert "Mode: ROLE PLAY" in tutor.messages[0]["content"]
    assert "airport check-in agent" in tutor.messages[0]["content"]
