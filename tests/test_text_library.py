"""Тесты библиотеки текстов — TextRepository + TextLibraryService."""

import os
import tempfile

import aiosqlite
import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def db():
    """Создаёт временную БД для каждого теста."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_path = tmp.name
    tmp.close()

    from bot.db import init_db
    await init_db(db_path)

    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        yield conn

    os.unlink(db_path)


@pytest_asyncio.fixture
async def seeded_db(db):
    """БД с засеянными текстами."""
    from bot.services.text_library_service import TextLibraryService, seed_texts
    await seed_texts(conn=db)
    service = TextLibraryService(db)
    yield db, service
    await service.close()


# ── TextRepository ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_text(db):
    """Создание текста (word_count вычисляется из content)."""
    from bot.db import TextRepository
    repo = TextRepository(db)
    text = await repo.create(
        title="Hello World",
        level="A1",
        category="daily_life",
        content="Hello. My name is John.",
    )
    assert text is not None
    assert text.title == "Hello World"
    assert text.level == "A1"
    assert text.category == "daily_life"
    assert text.word_count == 5  # 5 слов в content


@pytest.mark.asyncio
async def test_get_text_by_id(db):
    """Получение текста по ID через get()."""
    from bot.db import TextRepository
    repo = TextRepository(db)
    created = await repo.create(
        title="Test", level="B1", category="science", content="Tech content here.",
    )
    fetched = await repo.get(created.id)
    assert fetched is not None
    assert fetched.title == "Test"
    assert fetched.level == "B1"


@pytest.mark.asyncio
async def test_get_active_text(db):
    """get_active возвращает только активные тексты."""
    from bot.db import TextRepository
    repo = TextRepository(db)
    text = await repo.create(
        title="Active", level="A1", category="daily_life", content="Active text.",
    )
    active = await repo.get_active(text.id)
    assert active is not None

    await repo.delete(text.id)
    deleted = await repo.get_active(text.id)
    assert deleted is None


@pytest.mark.asyncio
async def test_list_by_level(db):
    """Список текстов по уровню."""
    from bot.db import TextRepository
    repo = TextRepository(db)
    await repo.create(title="A1_1", level="A1", category="daily_life", content="A B C")
    await repo.create(title="A1_2", level="A1", category="daily_life", content="D E F")
    await repo.create(title="B1_1", level="B1", category="daily_life", content="G H I")

    texts = await repo.list_by_level("A1")
    assert len(texts) == 2


@pytest.mark.asyncio
async def test_list_by_level_and_category(db):
    """Список текстов по уровню + категории."""
    from bot.db import TextRepository
    repo = TextRepository(db)
    await repo.create(title="T1", level="A1", category="daily_life", content="X Y Z")
    await repo.create(title="T2", level="A1", category="science", content="W V U")

    texts = await repo.list_by_level("A1", "daily_life")
    assert len(texts) == 1
    assert texts[0].title == "T1"


@pytest.mark.asyncio
async def test_list_by_category(db):
    """Список текстов по категории."""
    from bot.db import TextRepository
    repo = TextRepository(db)
    await repo.create(title="T1", level="A1", category="daily_life", content="A B")
    await repo.create(title="T2", level="A1", category="science", content="C D")
    await repo.create(title="T3", level="B1", category="science", content="E F")

    texts = await repo.list_by_category("science")
    assert len(texts) == 2
    assert all(t.category == "science" for t in texts)


@pytest.mark.asyncio
async def test_list_all(db):
    """Список всех активных текстов."""
    from bot.db import TextRepository
    repo = TextRepository(db)
    await repo.create(title="T1", level="A1", category="daily_life", content="A B")
    await repo.create(title="T2", level="B1", category="daily_life", content="C D")

    texts = await repo.list_all()
    assert len(texts) == 2


@pytest.mark.asyncio
async def test_count_by_level(db):
    """Количество текстов на уровне."""
    from bot.db import TextRepository
    repo = TextRepository(db)
    await repo.create(title="T1", level="A1", category="daily_life", content="A B")
    await repo.create(title="T2", level="A1", category="daily_life", content="C D")
    await repo.create(title="T3", level="C1", category="daily_life", content="E F G")

    assert await repo.count_by_level("A1") == 2
    assert await repo.count_by_level("C1") == 1
    assert await repo.count_by_level("B2") == 0


@pytest.mark.asyncio
async def test_list_levels(db):
    """Список уникальных уровней."""
    from bot.db import TextRepository
    repo = TextRepository(db)
    await repo.create(title="T1", level="A1", category="daily_life", content="A B")
    await repo.create(title="T2", level="B1", category="daily_life", content="C D")
    await repo.create(title="T3", level="A1", category="daily_life", content="E F")

    levels = await repo.list_levels()
    assert "A1" in levels
    assert "B1" in levels
    assert len(levels) == 2


@pytest.mark.asyncio
async def test_list_categories(db):
    """Список уникальных категорий."""
    from bot.db import TextRepository
    repo = TextRepository(db)
    await repo.create(title="T1", level="A1", category="daily_life", content="A B")
    await repo.create(title="T2", level="B1", category="science", content="C D")

    cats = await repo.list_categories()
    assert "daily_life" in cats
    assert "science" in cats


@pytest.mark.asyncio
async def test_delete_text(db):
    """Soft-delete текста (is_active = 0)."""
    from bot.db import TextRepository
    repo = TextRepository(db)
    text = await repo.create(title="T", level="A1", category="daily_life", content="A B")

    await repo.delete(text.id)
    fetched = await repo.get(text.id)
    assert fetched is not None
    assert fetched.is_active is False

    # Не показывается в активных списках
    all_texts = await repo.list_all()
    assert text.id not in [t.id for t in all_texts]


# ── TextProgressRepository ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_and_complete_progress(db):
    """Начать и завершить чтение текста."""
    from bot.db import TextProgressRepository, TextRepository

    text_repo = TextRepository(db)
    text = await text_repo.create(title="T", level="A1", category="daily_life", content="Hi there")

    prog_repo = TextProgressRepository(db)
    prog = await prog_repo.start(user_id=1, text_id=text.id)
    assert prog is not None
    assert prog.user_id == 1
    assert prog.status == "started"

    await prog_repo.complete(user_id=1, text_id=text.id)
    completed = await prog_repo.get(user_id=1, text_id=text.id)
    assert completed.status == "completed"


@pytest.mark.asyncio
async def test_get_progress(db):
    """Получить прогресс пользователя по тексту."""
    from bot.db import TextProgressRepository, TextRepository

    text_repo = TextRepository(db)
    text = await text_repo.create(title="T", level="A1", category="daily_life", content="Hi there")

    prog_repo = TextProgressRepository(db)
    await prog_repo.start(user_id=1, text_id=text.id)

    prog = await prog_repo.get(user_id=1, text_id=text.id)
    assert prog is not None
    assert prog.status == "started"

    # Нет прогресса для другого пользователя
    prog2 = await prog_repo.get(user_id=2, text_id=text.id)
    assert prog2 is None


@pytest.mark.asyncio
async def test_increment_words(db):
    """Увеличение счётчика слов."""
    from bot.db import TextProgressRepository, TextRepository

    text_repo = TextRepository(db)
    text = await text_repo.create(title="T", level="A1", category="daily_life", content="Hi there")

    prog_repo = TextProgressRepository(db)
    await prog_repo.start(user_id=1, text_id=text.id)

    await prog_repo.increment_words(user_id=1, text_id=text.id)
    await prog_repo.increment_words(user_id=1, text_id=text.id, count=3)

    prog = await prog_repo.get(user_id=1, text_id=text.id)
    assert prog.words_learned == 4


@pytest.mark.asyncio
async def test_stats(db):
    """Статистика чтения пользователя."""
    from bot.db import TextProgressRepository, TextRepository

    text_repo = TextRepository(db)
    t1 = await text_repo.create(title="T1", level="A1", category="daily_life", content="A B C")
    t2 = await text_repo.create(title="T2", level="B1", category="science", content="D E F")

    prog_repo = TextProgressRepository(db)
    await prog_repo.start(user_id=1, text_id=t1.id)
    await prog_repo.complete(user_id=1, text_id=t1.id)
    await prog_repo.start(user_id=1, text_id=t2.id)

    stats = await prog_repo.stats(user_id=1)
    assert stats["total_started"] == 2
    assert stats["completed"] == 1
    assert "words_learned" in stats


# ── TextBookmarkRepository ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_and_list_bookmarks(db):
    """Добавление и список закладок."""
    from bot.db import TextBookmarkRepository, TextRepository

    text_repo = TextRepository(db)
    text = await text_repo.create(title="T", level="A1", category="daily_life", content="Hi there")

    bm_repo = TextBookmarkRepository(db)
    bm = await bm_repo.add(user_id=1, text_id=text.id, paragraph_index=2)
    assert bm is not None
    assert bm.user_id == 1
    assert bm.paragraph_index == 2

    bookmarks = await bm_repo.list_for_user(user_id=1)
    assert len(bookmarks) == 1
    assert bookmarks[0].paragraph_index == 2


@pytest.mark.asyncio
async def test_delete_bookmark(db):
    """Удаление закладки."""
    from bot.db import TextBookmarkRepository, TextRepository

    text_repo = TextRepository(db)
    text = await text_repo.create(title="T", level="A1", category="daily_life", content="Hi there")

    bm_repo = TextBookmarkRepository(db)
    bm1 = await bm_repo.add(user_id=1, text_id=text.id, paragraph_index=0)
    await bm_repo.add(user_id=1, text_id=text.id, paragraph_index=2)

    await bm_repo.remove(bm1.id)
    bookmarks = await bm_repo.list_for_user(user_id=1)
    assert len(bookmarks) == 1
    assert bookmarks[0].paragraph_index == 2


# ── TextLibraryService ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_seed_texts(seeded_db):
    """Засев текстов — минимум 10 штук A1-C2."""
    db, service = seeded_db
    texts = await service.list_texts()
    assert len(texts) >= 10

    levels = set(t.level for t in texts)
    for lvl in ("A1", "A2", "B1", "B2", "C1", "C2"):
        assert lvl in levels, f"Missing level {lvl}"


@pytest.mark.asyncio
async def test_seed_is_idempotent(db):
    """Повторный seed не создаёт дубликатов."""
    from bot.services.text_library_service import seed_texts
    await seed_texts(conn=db)
    from bot.db import TextRepository
    repo = TextRepository(db)
    count1 = len(await repo.list_all())
    await seed_texts(conn=db)
    count2 = len(await repo.list_all())
    assert count1 == count2


@pytest.mark.asyncio
async def test_list_by_level_service(seeded_db):
    """Фильтрация по уровню через сервис."""
    db, service = seeded_db
    texts = await service.list_texts(level="A1")
    assert len(texts) >= 2
    assert all(t.level == "A1" for t in texts)


@pytest.mark.asyncio
async def test_list_by_category_service(seeded_db):
    """Фильтрация по категории через сервис."""
    db, service = seeded_db
    texts = await service.list_texts(category="daily_life")
    assert len(texts) >= 2
    assert all(t.category == "daily_life" for t in texts)


@pytest.mark.asyncio
async def test_list_by_level_and_category(seeded_db):
    """Фильтрация по уровню + категории."""
    db, service = seeded_db
    texts = await service.list_texts(level="A1", category="daily_life")
    assert len(texts) >= 1
    assert all(t.level == "A1" and t.category == "daily_life" for t in texts)


@pytest.mark.asyncio
async def test_get_text_service(seeded_db):
    """Получение одного текста через сервис."""
    db, service = seeded_db
    texts = await service.list_texts()
    assert len(texts) > 0

    text = await service.get_text(texts[0].id)
    assert text is not None
    assert text.title == texts[0].title


@pytest.mark.asyncio
async def test_get_text_not_found(seeded_db):
    """Несуществующий текст возвращает None."""
    db, service = seeded_db
    text = await service.get_text(99999)
    assert text is None


@pytest.mark.asyncio
async def test_get_text_with_progress(seeded_db):
    """Текст с прогрессом пользователя."""
    db, service = seeded_db
    texts = await service.list_texts()
    text_id = texts[0].id

    await service.start_reading(user_id=42, text_id=text_id)
    t, p = await service.get_text_with_progress(42, text_id)
    assert t is not None
    assert p is not None
    assert p.status == "started"

    # Другой пользователь — без прогресса
    t2, p2 = await service.get_text_with_progress(99, text_id)
    assert t2 is not None
    assert p2 is None


@pytest.mark.asyncio
async def test_split_paragraphs(seeded_db):
    """Разбивка текста на абзацы."""
    db, service = seeded_db
    text = "Line one.\n\nLine two.\n\nLine three."
    paragraphs = service.split_paragraphs(text)
    assert len(paragraphs) == 3
    assert paragraphs[0] == "Line one."
    assert paragraphs[1] == "Line two."
    assert paragraphs[2] == "Line three."


@pytest.mark.asyncio
async def test_split_paragraphs_single_line(seeded_db):
    """Одна строка — один абзац."""
    db, service = seeded_db
    paragraphs = service.split_paragraphs("Just one line.")
    assert len(paragraphs) == 1
    assert paragraphs[0] == "Just one line."


@pytest.mark.asyncio
async def test_split_paragraphs_empty(seeded_db):
    """Пустой текст — пустой список."""
    db, service = seeded_db
    paragraphs = service.split_paragraphs("")
    assert paragraphs == []


@pytest.mark.asyncio
async def test_start_and_complete_reading_service(seeded_db):
    """Начать и завершить чтение через сервис."""
    db, service = seeded_db
    texts = await service.list_texts()
    text_id = texts[0].id

    await service.start_reading(user_id=42, text_id=text_id)

    stats = await service.get_progress_stats(user_id=42)
    assert stats["total_started"] == 1
    assert stats["completed"] == 0

    await service.complete_reading(user_id=42, text_id=text_id)
    stats = await service.get_progress_stats(user_id=42)
    assert stats["completed"] == 1


@pytest.mark.asyncio
async def test_get_progress_for_texts_service(seeded_db):
    """Прогресс по нескольким текстам."""
    db, service = seeded_db
    texts = await service.list_texts()
    target = texts[:3]

    await service.start_reading(user_id=7, text_id=target[0].id)
    await service.complete_reading(user_id=7, text_id=target[0].id)
    await service.start_reading(user_id=7, text_id=target[1].id)

    progress_map = await service.get_progress_for_texts(user_id=7, texts=target)
    assert progress_map[target[0].id] is not None
    assert progress_map[target[0].id].status == "completed"
    assert progress_map[target[1].id] is not None
    assert progress_map[target[1].id].status == "started"
    assert target[2].id in progress_map


@pytest.mark.asyncio
async def test_add_and_list_bookmarks_service(seeded_db):
    """Закладки через сервис."""
    db, service = seeded_db
    texts = await service.list_texts()
    text_id = texts[0].id

    bm = await service.add_bookmark(user_id=5, text_id=text_id, paragraph_index=1)
    assert bm is not None
    assert bm.paragraph_index == 1

    bookmarks = await service.list_bookmarks(user_id=5)
    assert len(bookmarks) == 1


@pytest.mark.asyncio
async def test_add_word_updates_progress(seeded_db):
    """Добавление слова обновляет счётчик."""
    db, service = seeded_db
    texts = await service.list_texts()
    text_id = texts[0].id

    await service.start_reading(user_id=9, text_id=text_id)
    await service.add_word(user_id=9, text_id=text_id)

    stats = await service.get_progress_stats(user_id=9)
    assert stats["words_learned"] >= 1


@pytest.mark.asyncio
async def test_get_levels_with_counts(seeded_db):
    """Уровни с количеством текстов."""
    db, service = seeded_db
    levels = await service.get_levels_with_counts()
    assert len(levels) >= 6  # A1-C2
    all_levels = [l["level"] for l in levels]
    # Порядок: A1, A2, B1, B2, C1, C2
    assert all_levels == sorted(all_levels)
    assert all(l["count"] >= 1 for l in levels)


@pytest.mark.asyncio
async def test_get_categories_with_counts(seeded_db):
    """Категории с количеством текстов."""
    db, service = seeded_db
    cats = await service.get_categories_with_counts()
    assert len(cats) >= 4
    assert all("category" in c and "count" in c and "label" in c for c in cats)
    assert all(int(c["count"]) > 0 for c in cats)


@pytest.mark.asyncio
async def test_get_level_label():
    """Метка уровня."""
    from bot.services.text_library_service import get_level_label
    label = get_level_label("B2")
    assert "Выше среднего" in label


@pytest.mark.asyncio
async def test_get_category_label():
    """Метка категории."""
    from bot.services.text_library_service import get_category_label
    label = get_category_label("daily_life")
    assert "Повседневная" in label


@pytest.mark.asyncio
async def test_get_category_label_unknown():
    """Неизвестная категория возвращает исходное значение."""
    from bot.services.text_library_service import get_category_label
    label = get_category_label("unknown_category")
    assert label == "unknown_category"


@pytest.mark.asyncio
async def test_texts_ordered(seeded_db):
    """Тексты отсортированы по уровню внутри списка."""
    db, service = seeded_db
    texts = await service.list_texts()
    level_order = {"A1": 0, "A2": 1, "B1": 2, "B2": 3, "C1": 4, "C2": 5}

    prev = -1
    for t in texts:
        cur = level_order.get(t.level, 99)
        assert cur >= prev, f"{t.title} ({t.level}) out of order"
        prev = cur


@pytest.mark.asyncio
async def test_generate_questions_no_api_key(seeded_db):
    """Генерация вопросов без API-ключа возвращает [].

    Тест пропускается, если ключ есть (генерация реальная).
    """
    from bot.services.text_library_service import OPENROUTER_URL

    key = os.environ.get("OPENROUTER_API_KEY", "")
    if key:
        pytest.skip("API key present — real generation test")

    db, service = seeded_db
    text = (await service.list_texts())[0]
    questions = await service.generate_questions(
        text.title, text.content, text.level, count=3,
    )
    assert questions == []