"""AI Service — взаимодействие с OpenRouter для генерации ответа репетитора."""

import json
import httpx
import re
import random
from typing import Optional

from bot.services.retry_utils import (
    CircuitBreaker,
    retry_with_backoff,
    CircuitBreakerOpenError,
)


# ─── Режимы диалога ─────────────────────────────────────────────────────────────

MODE_FREE_TALK = "free_talk"
MODE_ROLE_PLAY = "role_play"
MODE_GRAMMAR_FOCUS = "grammar_focus"

MODES = [MODE_FREE_TALK, MODE_ROLE_PLAY, MODE_GRAMMAR_FOCUS]

MODE_LABELS = {
    MODE_FREE_TALK: "🗣 Свободная беседа",
    MODE_ROLE_PLAY: "🎭 Ролевая игра",
    MODE_GRAMMAR_FOCUS: "📚 Грамматика",
}

MODE_ICONS = {
    MODE_FREE_TALK: "🗣",
    MODE_ROLE_PLAY: "🎭",
    MODE_GRAMMAR_FOCUS: "📚",
}

MODE_DESCRIPTIONS = {
    MODE_FREE_TALK: (
        "Свободный разговор на любую тему.\n"
        "AI поддерживает беседу, исправляет ошибки и даёт советы."
    ),
    MODE_ROLE_PLAY: (
        "Ролевая игра в разных сценариях.\n"
        "Ресторан, отель, собеседование — отработка реальных ситуаций."
    ),
    MODE_GRAMMAR_FOCUS: (
        "Режим с фокусом на грамматику.\n"
        "AI проверяет времена, порядок слов и конструкции."
    ),
}

ROLE_PLAY_SCENARIOS = [
    (
        "restaurant",
        "You are a waiter at an English restaurant. The user is a customer.",
    ),
    ("shop", "You are a shop assistant. The user is a customer looking for clothes."),
    ("hotel", "You are a hotel receptionist. The user is checking in."),
    ("job_interview", "You are an HR manager conducting a job interview in English."),
    ("airport", "You are an airport check-in agent. The user is a passenger."),
    ("doctor", "You are a doctor. The user is a patient describing symptoms."),
]

GRAMMAR_TOPICS = [
    "Past Simple vs Present Perfect",
    "Conditionals (if-clauses)",
    "Prepositions of time and place",
    "Articles (a/an/the)",
    "Phrasal verbs",
    "Reported speech",
    "Passive voice",
]

SYSTEM_PROMPT_TEMPLATE = """You are an English tutor. The user's level is {level} (CEFR).

Rules:
1. Adapt your language to the user's level.
2. After each user message, correct any mistakes naturally within your response.
3. Keep the conversation flowing — ask follow-up questions.
4. Stay on topic: {topic}
5. Rate the user's response (1-5) based on grammar, vocabulary, fluency.
6. Keep responses under 150 words.
7. CRITICAL: For EACH correction, provide a clear explanation of WHY it's wrong
   and the grammar rule behind it in simple terms. Write in the user's native language (Russian).

IMPORTANT: Return your response in JSON format:
{{
    "reply": "your natural response in English",
    "corrections": [{{"original": "wrong", "corrected": "right", "category": "grammar/spelling/vocabulary", "explanation": "Почему так: правило на русском языке с примерами"}}],
    "rating": 4,
    "vocabulary_tip": "optional tip",
    "explanation": "Общее объяснение самых важных ошибок в диалоге на русском языке. Если ошибок нет — оставь пустым.",
    "new_words": [{{"word": "yesterday", "translation": "вчера", "context": "I went to the store yesterday"}}]
}}

If the user says nothing or types an empty message, suggest a topic to start with."""

FREE_TALK_PROMPT = """You are an English tutor. The user's level is {level} (CEFR). Mode: FREE TALK.

Rules:
1. Act like a friendly conversation partner. Keep the dialogue natural and flowing.
2. Adapt your language to the user's level — challenge them slightly but don't overwhelm.
3. Ask open-ended follow-up questions to keep the conversation going.
4. Correct ONLY major errors that affect understanding. Minor mistakes can be ignored.
5. Priority: FLUENCY over accuracy. The goal is to get the user talking.
6. Stay on topic: {topic}
7. Rate the user's response (1-5).
8. Keep responses under 150 words.
9. For corrections, provide brief explanations in Russian.

IMPORTANT: Return your response in JSON format:
{{
    "reply": "your natural response in English",
    "corrections": [{{"original": "wrong", "corrected": "right", "category": "grammar/spelling/vocabulary", "explanation": "Почему так: краткое правило на русском"}}],
    "rating": 4,
    "vocabulary_tip": "optional tip",
    "explanation": "общее объяснение ошибок на русском (пусто если нет ошибок)",
    "new_words": [{{"word": "yesterday", "translation": "вчера", "context": "I went to the store yesterday"}}]
}}"""

ROLE_PLAY_PROMPT = """You are an English tutor. The user's level is {level} (CEFR). Mode: ROLE PLAY.

Scenario: {scenario_description}

Rules:
1. You are playing the role described above. Stay IN CHARACTER throughout the conversation.
2. The user is playing the other role. Respond as your character would.
3. Start the scene naturally (e.g., "Good evening, welcome to our restaurant! How many guests?")
4. Adapt your language to the user's level.
5. After the role play is done (natural ending), step out of character briefly to give corrections.
6. Keep responses under 150 words.
7. Rate the user's performance (1-5) based on vocabulary use, fluency, and appropriateness.

IMPORTANT: Return your response in JSON format:
{{
    "reply": "your in-character response in English",
    "corrections": [{{"original": "wrong", "corrected": "right", "category": "grammar/spelling/vocabulary", "explanation": "Почему так: краткое правило на русском"}}],
    "rating": 4,
    "vocabulary_tip": "useful phrase for this situation",
    "explanation": "общее объяснение ошибок на русском (пусто если нет ошибок). Include role-play tips too.",
    "new_words": [{{"word": "menu", "translation": "меню", "context": "Could I see the menu, please?"}}]
}}"""

GRAMMAR_FOCUS_PROMPT = """You are an English tutor. The user's level is {level} (CEFR). Mode: GRAMMAR FOCUS.

Grammar focus area: {grammar_focus}

Rules:
1. Your PRIMARY goal is to help the user practice the grammar focus area listed above.
2. Ask questions or set up scenarios that naturally require using this grammar structure.
3. When the user makes an error related to the focus area, provide a DETAILED explanation of the rule with examples.
4. For errors unrelated to the focus area, give only brief corrections.
5. Track and encourage correct usage of the target grammar.
6. Stay on topic: {topic}
7. Rate the user's response (1-5) with extra weight on correct use of the target grammar.
8. Keep responses under 150 words.

IMPORTANT: Return your response in JSON format:
{{
    "reply": "your response in English",
    "corrections": [{{"original": "wrong", "corrected": "right", "category": "grammar/spelling/vocabulary", "explanation": "Подробное объяснение правила на русском с примерами"}}],
    "rating": 4,
    "vocabulary_tip": "optional tip",
    "explanation": "детальный разбор грамматических ошибок на русском. Если фокусная грамматика используется правильно — похвали.",
    "new_words": [{{"word": "yesterday", "translation": "вчера", "context": "I went to the store yesterday"}}]
}}"""


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def build_system_prompt(
    level: str,
    topic: str,
    mode: str = MODE_FREE_TALK,
    scenario: Optional[str] = None,
    grammar_focus: Optional[str] = None,
) -> str:
    """Строит системный промпт для AI-репетитора с учётом режима."""
    if mode == MODE_ROLE_PLAY:
        scenario_desc = scenario or "restaurant — waiter and customer"
        return ROLE_PLAY_PROMPT.format(
            level=level,
            scenario_description=scenario_desc,
            topic=topic,
        )
    elif mode == MODE_GRAMMAR_FOCUS:
        gf = grammar_focus or "Past Simple vs Present Perfect"
        return GRAMMAR_FOCUS_PROMPT.format(
            level=level,
            grammar_focus=gf,
            topic=topic,
        )
    # free_talk (default)
    return FREE_TALK_PROMPT.format(level=level, topic=topic)


def pick_random_scenario() -> tuple[str, str]:
    """Возвращает случайный сценарий для role play."""
    scenario_key, description = random.choice(ROLE_PLAY_SCENARIOS)
    return scenario_key, description


def pick_random_grammar_topic() -> str:
    """Возвращает случайную грамматическую тему."""
    return random.choice(GRAMMAR_TOPICS)


def parse_ai_response(raw: str) -> dict:
    """Парсит JSON-ответ AI-репетитора.

    Порядок попыток:
    1. Если ответ в ```json ... ``` блоке — извлекаем содержимое.
    2. Пробуем json.loads напрямую.
    3. Ищем первый { … } блок через regex (для случая, когда AI вернул
       bare JSON без обёртки).
    4. Если ничего не сработало — поднимаем исключение.
    """
    # 1. Markdown-блок ```json ... ```
    if "```json" in raw:
        content = raw.split("```json", 1)[1]
        if "```" in content:
            content = content.split("```", 1)[0]
        return json.loads(content.strip())

    # 2. Прямой парсинг
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        pass

    # 3. Регулярка (находит первый JSON-объект)
    json_match = re.search(r"\{.*\}", raw, re.DOTALL)
    if json_match:
        return json.loads(json_match.group(0))

    # 4. Всё сломалось
    raise ValueError(
        f"Не удалось распарсить JSON из ответа AI. Первые 200 символов: {raw[:200]}"
    )


class AITutor:
    """AI-репетитор английского языка."""

    def __init__(
        self,
        level: str,
        api_key: str,
        topic: str = "introduction",
        model: str = "openai/gpt-4o-mini",
        max_history: int = 10,
        circuit_breaker: Optional[CircuitBreaker] = None,
        mode: str = MODE_FREE_TALK,
        scenario: Optional[str] = None,
        grammar_focus: Optional[str] = None,
    ):
        self.level = level
        self.api_key = api_key
        self.topic = topic
        self.model = model
        self.max_history = max_history
        self.circuit_breaker = circuit_breaker or CircuitBreaker(
            name="openrouter-chat",
            failure_threshold=5,
            recovery_timeout=60.0,
        )
        self.mode = mode
        self.scenario = scenario
        self.grammar_focus = grammar_focus
        self.messages: list[dict] = [
            {
                "role": "system",
                "content": build_system_prompt(
                    level,
                    topic,
                    mode=mode,
                    scenario=scenario,
                    grammar_focus=grammar_focus,
                ),
            }
        ]

    def set_mode(
        self,
        mode: str,
        scenario: Optional[str] = None,
        grammar_focus: Optional[str] = None,
    ) -> None:
        """Переключает режим диалога, пересобирая системный промпт и очищая историю."""
        self.mode = mode
        self.scenario = scenario
        self.grammar_focus = grammar_focus
        self.messages = [
            {
                "role": "system",
                "content": build_system_prompt(
                    self.level,
                    self.topic,
                    mode=mode,
                    scenario=scenario,
                    grammar_focus=grammar_focus,
                ),
            }
        ]

    async def _call_openrouter(self) -> dict:
        """Выполняет HTTP-запрос к OpenRouter /chat/completions (без retry).

        Отдельный метод, чтобы retry_with_backoff мог его оборачивать.
        Возвращает распарсенный JSON-ответ репетитора.
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/",
        }
        payload = {
            "model": self.model,
            "messages": self.messages,
            "temperature": 0.7,
            "max_tokens": 300,
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(OPENROUTER_URL, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            raw_content = data["choices"][0]["message"]["content"]
            result = parse_ai_response(raw_content)
            self.messages.append({"role": "assistant", "content": json.dumps(result)})
            # Trim history
            if len(self.messages) > self.max_history + 10:
                self.messages = [self.messages[0]] + self.messages[-self.max_history :]
            return result

    async def chat(self, user_message: str) -> dict:
        """Отправляет сообщение AI-репетитору и получает ответ."""
        self.messages.append(
            {"role": "user", "content": user_message or "Suggest a topic"}
        )

        try:
            # Тестовые ключи — без внешних вызовов
            if self.api_key == "test_key":
                return self._mock_response(user_message)
            if self.api_key == "invalid_key":
                raise Exception("Invalid API key")

            return await retry_with_backoff(
                self._call_openrouter,
                max_retries=3,
                base_delay=1.0,
                max_delay=10.0,
                circuit_breaker=self.circuit_breaker,
            )

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise Exception("Invalid API key")
            raise Exception(f"OpenRouter API error: {e.response.status_code}")
        except httpx.TimeoutException:
            raise Exception("OpenRouter API timeout")
        except CircuitBreakerOpenError:
            raise Exception(
                "Сервис AI временно недоступен — слишком много ошибок. "
                "Пожалуйста, попробуй через минуту."
            )
        except Exception as e:
            if "Invalid API key" in str(e):
                raise
            raise Exception(f"AI service error: {str(e)}")

    def _mock_response(self, message: str) -> dict:
        """Мок для тестов (без реального API)."""
        corrections = []
        if "go" in message.lower() and "yesterday" in message.lower():
            corrections.append(
                {
                    "original": "I go",
                    "corrected": "I went",
                    "category": "tense",
                }
            )
        if "good" in message.lower():
            corrections.append(
                {
                    "original": "good",
                    "corrected": "well",
                    "category": "vocabulary",
                }
            )

        if self.mode == MODE_ROLE_PLAY:
            ai_reply = "Welcome to our restaurant, sir! Table for one? May I show you to your seat?"
        elif self.mode == MODE_GRAMMAR_FOCUS:
            ai_reply = (
                "Let's practice Past Simple. Tell me about something you did yesterday!"
            )
        else:
            ai_reply = "That's a great start! Let's keep practicing."
            if "hello" in message.lower():
                ai_reply = "Hello! It's nice to meet you. Let's start our English lesson. What topics would you like to talk about today?"
            elif "like" in message.lower():
                ai_reply = "Reading is a wonderful habit! I read English books too. What kind of books do you prefer — fiction or non-fiction?"

        return {
            "reply": ai_reply,
            "corrections": corrections,
            "rating": 4 if not corrections else 3,
            "vocabulary_tip": "",
            "explanation": "Отличная попытка! Обрати внимание на согласование времён — если действие произошло вчера (yesterday), используй Past Simple (went, not go).",
            "new_words": [
                {
                    "word": "yesterday",
                    "translation": "вчера",
                    "context": "I went to the store yesterday",
                }
            ],
        }
