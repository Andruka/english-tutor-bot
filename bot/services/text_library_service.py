"""Сервис библиотеки текстов для чтения.

Предоставляет: каталог текстов по уровням/категориям, чтение с пагинацией,
прогресс пользователя, вопросы на понимание через AI, закладки.
"""

import json
import os
from typing import Optional

import httpx

from bot.db import (
    Text,
    TextBookmark,
    TextBookmarkRepository,
    TextProgressRepository,
    TextRepository,
    UserTextProgress,
    get_conn,
)


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


# ── Категории текстов ─────────────────────────────────────────────────────

CATEGORIES = [
    ("daily_life", "Повседневная жизнь"),
    ("travel", "Путешествия"),
    ("culture", "Культура и искусство"),
    ("science", "Наука и технологии"),
    ("business", "Бизнес"),
    ("story", "История / рассказ"),
    ("nature", "Природа"),
]

CATEGORY_LABELS = dict(CATEGORIES)

CEFR_ORDER = {"A1": 0, "A2": 1, "B1": 2, "B2": 3, "C1": 4, "C2": 5}
ALL_LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]


# ── Seed-тексты ──────────────────────────────────────────────────────────

SEED_TEXTS: list[dict] = [
    # ── A1 ──
    {
        "title": "My Morning",
        "level": "A1",
        "category": "daily_life",
        "content": (
            "Every day I wake up at seven o'clock. I brush my teeth and "
            "wash my face. Then I have breakfast. I eat bread with butter "
            "and drink a cup of tea. After breakfast I go to work. I work "
            "in an office. I like my job. In the evening I come home and "
            "have dinner with my family."
        ),
    },
    {
        "title": "A Trip to the Park",
        "level": "A1",
        "category": "nature",
        "content": (
            "It is a sunny day. Tom and his sister go to the park. They see "
            "green trees and beautiful flowers. There is a big lake in the "
            "park. Ducks swim in the lake. Tom and his sister feed the ducks. "
            "Then they play football on the grass. They are very happy. "
            "In the afternoon they go home."
        ),
    },
    # ── A2 ──
    {
        "title": "A Weekend in the Countryside",
        "level": "A2",
        "category": "travel",
        "content": (
            "Last weekend my family and I visited my grandparents who live "
            "in a small village. The village is about two hours from the city. "
            "When we arrived, my grandmother was cooking lunch in the kitchen. "
            "The smell was wonderful! After lunch, I helped my grandfather in "
            "the garden. We picked vegetables and watered the plants. In the "
            "evening, we sat outside and looked at the stars. It was so quiet "
            "and peaceful. I really enjoyed the weekend. I want to visit them "
            "again next month."
        ),
    },
    {
        "title": "My Favorite Restaurant",
        "level": "A2",
        "category": "daily_life",
        "content": (
            "There is a small Italian restaurant near my house. The waiters "
            "are very friendly and the food is delicious. I usually go there "
            "with my friends on Friday evenings. My favorite dish is pasta "
            "with tomato sauce and cheese. The restaurant also makes the "
            "best pizza in town. The prices are not very expensive. A pizza "
            "costs about ten dollars. I like the atmosphere there. The walls "
            "are decorated with pictures of Italy and they always play nice "
            "music. If you like Italian food, you should try this restaurant."
        ),
    },
    # ── B1 ──
    {
        "title": "How Smartphones Changed Our Lives",
        "level": "B1",
        "category": "science",
        "content": (
            "Smartphones have completely changed the way we live and "
            "communicate. Twenty years ago, people used mobile phones only "
            "to make calls and send text messages. Today, a smartphone can "
            "do thousands of different things. We use them to take photos, "
            "navigate in unknown places, check the weather, read news, and "
            "stay in touch with friends through social media. However, there "
            "are also negative effects. Many people spend too much time on "
            "their phones. They look at screens during meals, while walking, "
            "and even before going to sleep. Studies show that too much "
            "screen time can cause problems with sleep and concentration. "
            "The key is to find a balance between using technology and "
            "enjoying the real world around us."
        ),
    },
    {
        "title": "The Story of the Silk Road",
        "level": "B1",
        "category": "culture",
        "content": (
            "The Silk Road was not a single road but a network of trade "
            "routes that connected China with the Mediterranean Sea. It "
            "was used for more than fifteen hundred years, from around "
            "130 BCE to the 15th century. Merchants traveled thousands of "
            "kilometers across deserts and mountains to trade silk, spices, "
            "gold, and other valuable goods. But the Silk Road was not only "
            "about trade. It also helped spread ideas, religions, and "
            "technologies between different civilizations. Buddhism traveled "
            "from India to China along these routes. Papermaking and gunpowder "
            "also moved from East to West. Today, the Silk Road reminds us "
            "how connected our world has always been, even long before modern "
            "transportation and the internet."
        ),
    },
    # ── B2 ──
    {
        "title": "Climate Change: Causes and Solutions",
        "level": "B2",
        "category": "science",
        "content": (
            "Climate change is one of the most pressing challenges of our "
            "time. Scientists agree that the Earth's average temperature has "
            "risen significantly over the past century, primarily due to human "
            "activities. The burning of fossil fuels such as coal, oil, and "
            "natural gas releases greenhouse gases into the atmosphere. These "
            "gases trap heat, creating a greenhouse effect that warms the "
            "planet. The consequences are already visible: melting ice caps, "
            "rising sea levels, more frequent extreme weather events, and "
            "disruption of ecosystems. However, there is hope. Many countries "
            "have committed to reducing their carbon emissions. Renewable "
            "energy sources like solar and wind power are becoming cheaper and "
            "more efficient. Individuals can also make a difference by reducing "
            "waste, using public transportation, and supporting environmentally "
            "responsible businesses. The fight against climate change requires "
            "action at every level — from governments to individuals."
        ),
    },
    {
        "title": "The Art of Negotiation",
        "level": "B2",
        "category": "business",
        "content": (
            "Negotiation is an essential skill in both business and everyday "
            "life. At its core, negotiation is a process of communication "
            "between two or more parties who want to reach an agreement on "
            "a matter of mutual interest. Successful negotiators share several "
            "key qualities. First, they prepare thoroughly — they research the "
            "other party's needs, interests, and constraints before sitting "
            "down at the table. Second, they listen more than they speak. "
            "Understanding the other person's perspective is often more "
            "valuable than making a strong argument. Third, they focus on "
            "interests rather than positions. Instead of arguing over a fixed "
            "demand, they explore what each side truly wants and look for "
            "creative solutions that satisfy everyone. Finally, good "
            "negotiators know when to walk away. Not every deal is worth "
            "making, and having a clear BATNA — Best Alternative To a "
            "Negotiated Agreement — gives you the confidence to refuse "
            "unfavorable terms."
        ),
    },
    # ── C1 ──
    {
        "title": "The Psychology of Habit Formation",
        "level": "C1",
        "category": "science",
        "content": (
            "Habits shape our lives far more than we realize. Research in "
            "behavioral psychology suggests that approximately forty percent "
            "of our daily actions are driven by habit rather than conscious "
            "decision-making. Understanding how habits work can be a powerful "
            "tool for personal development. The habit loop, as described by "
            "Charles Duhigg, consists of three components: a cue, a routine, "
            "and a reward. The cue triggers the behavior, the routine is the "
            "behavior itself, and the reward is the benefit you gain from it. "
            "To change a habit, one must identify the cue and the reward, "
            "then substitute a different routine that delivers the same reward. "
            "This approach has been successfully applied in everything from "
            "weight loss programs to productivity systems. However, changing "
            "deeply ingrained habits requires more than just understanding the "
            "mechanism. It demands consistent effort, environmental design, "
            "and often social support. The most effective strategies combine "
            "small incremental changes with accountability systems. By "
            "redesigning our environment to make good habits easier and bad "
            "habits harder, we can gradually transform our automatic behaviors "
            "and, by extension, our lives."
        ),
    },
    {
        "title": "The Renaissance: A Cultural Revolution",
        "level": "C1",
        "category": "culture",
        "content": (
            "The Renaissance, spanning roughly from the fourteenth to the "
            "seventeenth century, represents one of the most transformative "
            "periods in European history. Originating in Italy and gradually "
            "spreading across the continent, it marked a profound shift in "
            "art, science, philosophy, and politics. The term 'Renaissance' "
            "literally means 'rebirth,' referring to the rediscovery of "
            "classical Greek and Roman texts that had been largely forgotten "
            "during the Middle Ages. This intellectual revival gave rise to "
            "humanism, a philosophical movement that emphasized human "
            "potential and achievement rather than solely divine matters. "
            "Artists like Leonardo da Vinci, Michelangelo, and Raphael "
            "revolutionized painting and sculpture with innovations in "
            "perspective, anatomy, and emotional expression. Meanwhile, "
            "the invention of the printing press by Gutenberg around 1440 "
            "democratized knowledge, making books accessible to a much "
            "broader audience. The Renaissance also produced groundbreaking "
            "scientific work — Copernicus challenged the geocentric model "
            "of the universe, while Galileo laid the foundations for modern "
            "physics. The legacy of the Renaissance is still felt today in "
            "our approach to education, art, and scientific inquiry."
        ),
    },
    # ── C2 ──
    {
        "title": "The Economics of Blockchain Technology",
        "level": "C2",
        "category": "business",
        "content": (
            "Blockchain technology, best known as the underlying infrastructure "
            "for cryptocurrencies such as Bitcoin and Ethereum, represents a "
            "paradigm shift in how economic value can be transferred and "
            "verified without centralized intermediaries. At its essence, a "
            "blockchain is a distributed ledger that maintains a continuously "
            "growing list of records — called blocks — which are linked and "
            "secured using cryptographic principles. What makes this "
            "technology economically significant is its potential to reduce "
            "or eliminate transaction costs associated with trust. In "
            "traditional economic exchanges, parties rely on institutions — "
            "banks, governments, legal systems — to verify transactions and "
            "enforce contracts. Blockchain enables a mechanism of consensus "
            "whereby network participants collectively validate transactions, "
            "rendering many of these intermediaries potentially obsolete. "
            "Smart contracts, self-executing agreements with terms directly "
            "written into code, further extend this capability by automating "
            "complex multi-party arrangements. However, the technology faces "
            "substantial challenges: scalability limitations, energy consumption "
            "concerns, regulatory uncertainty, and the inherent tension between "
            "decentralization and governance. The long-term economic "
            "implications of widespread blockchain adoption remain a subject "
            "of vigorous debate among economists and technologists alike."
        ),
    },
    {
        "title": "Phenomenology and the Nature of Consciousness",
        "level": "C2",
        "category": "culture",
        "content": (
            "Phenomenology, a philosophical movement founded by Edmund Husserl "
            "in the early twentieth century, seeks to examine the structures "
            "of conscious experience from a first-person perspective. Unlike "
            "empirical psychology, which treats consciousness as an object of "
            "scientific study, phenomenology brackets — or suspends judgment "
            "about — the external world in order to focus on the raw contents "
            "of experience itself. This method, which Husserl called the "
            "epoché, aims to return 'to the things themselves' — that is, "
            "to describe phenomena exactly as they appear to consciousness, "
            "without theoretical preconceptions. Martin Heidegger, Husserl's "
            "most famous student, extended this approach by emphasizing "
            "Dasein, or 'being-in-the-world,' arguing that consciousness "
            "cannot be understood in isolation from its concrete, temporal, "
            "and situated existence. Later thinkers like Maurice Merleau-Ponty "
            "incorporated embodiment into phenomenological analysis, "
            "demonstrating that perception is fundamentally shaped by the "
            "physical body. In contemporary cognitive science, phenomenology "
            "has found renewed relevance through the work of Francisco Varela "
            "and others who argue that a complete account of consciousness "
            "must integrate both objective neural correlates and subjective "
            "lived experience — a position known as neurophenomenology."
        ),
    },
]


def get_category_label(category_id: str) -> str:
    """Возвращает русскоязычную метку категории."""
    return CATEGORY_LABELS.get(category_id, category_id)


def get_level_label(level: str) -> str:
    """Возвращает русскоязычную метку уровня."""
    labels = {"A1": "A1 — Начальный", "A2": "A2 — Элементарный",
              "B1": "B1 — Средний", "B2": "B2 — Выше среднего",
              "C1": "C1 — Продвинутый", "C2": "C2 — Владение"}
    return labels.get(level, level)


def sort_levels(levels: list[str]) -> list[str]:
    """Сортирует уровни CEFR."""
    return sorted(levels, key=lambda l: CEFR_ORDER.get(l, 99))


# ── Основной сервис ──────────────────────────────────────────────────────


class TextLibraryService:
    """Сервис для работы с библиотекой текстов."""

    def __init__(self, conn):
        self.conn = conn
        self.text_repo = TextRepository(conn)
        self.progress_repo = TextProgressRepository(conn)
        self.bookmark_repo = TextBookmarkRepository(conn)

    @classmethod
    async def create(cls):
        """Создаёт сервис с новым подключением к БД."""
        conn = await get_conn()
        return cls(conn)

    async def close(self):
        """Закрывает подключение."""
        await self.conn.close()

    # ── Получение текстов ──────────────────────────────────────────────

    async def get_text(self, text_id: int) -> Optional[Text]:
        return await self.text_repo.get_active(text_id)

    async def get_text_with_progress(
        self, user_id: int, text_id: int,
    ) -> tuple[Optional[Text], Optional[UserTextProgress]]:
        text = await self.text_repo.get_active(text_id)
        progress = await self.progress_repo.get(user_id, text_id)
        return text, progress

    async def list_texts(
        self, level: str = "", category: str = "",
    ) -> list[Text]:
        if level and category:
            return await self.text_repo.list_by_level(level, category)
        if level:
            return await self.text_repo.list_by_level(level)
        if category:
            return await self.text_repo.list_by_category(category)
        return await self.text_repo.list_all()

    async def get_levels_with_counts(self) -> list[dict]:
        """Возвращает уровни с количеством текстов."""
        levels = sort_levels(await self.text_repo.list_levels())
        return [
            {"level": l, "label": get_level_label(l), "count": await self.text_repo.count_by_level(l)}
            for l in levels
        ]

    async def get_categories_with_counts(self) -> list[dict]:
        """Возвращает категории с количеством текстов."""
        categories = await self.text_repo.list_categories()
        result = []
        for c in categories:
            texts = await self.text_repo.list_by_category(c)
            result.append({
                "category": c,
                "label": get_category_label(c),
                "count": len(texts),
            })
        return result

    # ── Прогресс ────────────────────────────────────────────────────────

    async def start_reading(self, user_id: int, text_id: int) -> UserTextProgress:
        return await self.progress_repo.start(user_id, text_id)

    async def complete_reading(self, user_id: int, text_id: int) -> None:
        await self.progress_repo.complete(user_id, text_id)

    async def add_word(self, user_id: int, text_id: int) -> None:
        await self.progress_repo.increment_words(user_id, text_id)

    async def get_progress_stats(self, user_id: int) -> dict:
        return await self.progress_repo.stats(user_id)

    async def get_progress_for_texts(
        self, user_id: int, texts: list[Text],
    ) -> dict[int, UserTextProgress]:
        """Возвращает словарь text_id -> progress для списка текстов."""
        all_progress = await self.progress_repo.list_for_user(user_id)
        progress_map = {p.text_id: p for p in all_progress}
        return {t.id: progress_map.get(t.id) for t in texts}

    # ── Закладки ────────────────────────────────────────────────────────

    async def add_bookmark(
        self, user_id: int, text_id: int,
        paragraph_index: int = 0, note: str = "",
    ) -> TextBookmark:
        return await self.bookmark_repo.add(user_id, text_id, paragraph_index, note)

    async def list_bookmarks(self, user_id: int) -> list[TextBookmark]:
        return await self.bookmark_repo.list_for_user(user_id)

    async def remove_bookmark(self, bookmark_id: int) -> None:
        await self.bookmark_repo.remove(bookmark_id)

    # ── Разбивка текста на абзацы ───────────────────────────────────────

    def split_paragraphs(self, text: str) -> list[str]:
        """Разбивает текст на абзацы."""
        if not text or not text.strip():
            return []
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        return paragraphs or [text]

    def get_paragraph(
        self, text: Text, paragraph_index: int,
    ) -> Optional[str]:
        paragraphs = self.split_paragraphs(text.content)
        if 0 <= paragraph_index < len(paragraphs):
            return paragraphs[paragraph_index]
        return None

    def get_paragraph_count(self, text: Text) -> int:
        return len(self.split_paragraphs(text.content))

    # ── Вопросы на понимание (AI) ──────────────────────────────────────

    async def generate_questions(
        self, title: str, content: str, level: str, count: int = 3,
    ) -> list[dict]:
        """Генерирует вопросы на понимание текста через OpenRouter.

        Возвращает список словарей: [{"question": "...", "options": [...], "answer": 0}, ...]
        """
        prompt = (
            f"Read the following {level}-level English text and create {count} "
            f"multiple-choice comprehension questions in English.\n\n"
            f"Title: {title}\n\n"
            f"Text:\n{content}\n\n"
            f"Format your response as a JSON array of objects. Each object must have:\n"
            f"- \"question\": the question text (in English)\n"
            f"- \"options\": array of 4 answer choices (list of strings, in English)\n"
            f"- \"answer\": the 0-based index of the correct option\n\n"
            f"The questions should be appropriate for someone at CEFR level {level}. "
            f"Return ONLY the JSON array, no extra text."
        )

        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        if not api_key:
            return []

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/",
        }
        payload = {
            "model": "openai/gpt-4o-mini",
            "messages": [
                {
                    "role": "system",
                    "content": "You are a language teacher creating reading comprehension questions.",
                },
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 1024,
            "temperature": 0.7,
        }

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    OPENROUTER_URL, headers=headers, json=payload
                )
                response.raise_for_status()
                data = response.json()
                raw = data["choices"][0]["message"]["content"].strip()
                # Очищаем от markdown-кода, если модель завернула в ```json
                if raw.startswith("```"):
                    raw = raw.split("\n", 1)[-1]
                    raw = raw.rsplit("```", 1)[0].strip()
                questions = json.loads(raw)
                if isinstance(questions, list) and len(questions) > 0:
                    return questions
                return []
        except Exception:
            return []


# ── Seed-функция ────────────────────────────────────────────────────────


async def seed_texts(conn=None, force: bool = False) -> int:
    """Заполняет БД seed-текстами, если таблица пуста.

    Returns: количество добавленных текстов.
    """
    should_close = conn is None
    if conn is None:
        conn = await get_conn()

    try:
        repo = TextRepository(conn)

        if not force:
            existing = await repo.list_all()
            if existing:
                return 0

        added = 0
        for data in SEED_TEXTS:
            await repo.create(
                title=data["title"],
                level=data["level"],
                content=data["content"],
                category=data.get("category", "general"),
            )
            added += 1

        await conn.commit()
        return added
    finally:
        if should_close:
            await conn.close()