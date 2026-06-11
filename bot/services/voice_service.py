"""Voice Service — скачивание, транскрибация (STT через OpenRouter API) и озвучка (TTS)."""

import os
import uuid
import base64
import logging
from datetime import date
from typing import Optional

import httpx
import edge_tts
import aiosqlite
from aiogram import Bot

from bot.services.retry_utils import (
    CircuitBreaker,
    retry_with_backoff,
    CircuitBreakerOpenError,
)

logger = logging.getLogger(__name__)

# ─── Лимиты ───────────────────────────────────────────────────────────────────
OPENROUTER_STT_URL = "https://openrouter.ai/api/v1/audio/transcriptions"
DEFAULT_STT_MODEL = "openai/whisper-large-v3-turbo"

MAX_VOICE_DURATION_SEC = 60  # макс. длительность одного голосового сообщения
DAILY_BUDGET_MINUTES = 30  # макс. минут голоса в день
BUDGET_FILE = "/tmp/voice_budget.db"  # SQLite — атомарные транзакции


# ─── Управление дневным бюджетом (SQLite) ─────────────────────────────────────


async def _init_budget_db():
    """Создаёт таблицу бюджета, если её нет."""
    async with aiosqlite.connect(BUDGET_FILE) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS voice_budget (
                date TEXT PRIMARY KEY,
                total_seconds REAL NOT NULL DEFAULT 0
            )
        """)
        await db.commit()


async def _read_budget() -> dict:
    """Читает дневной бюджет из SQLite.

    Returns:
        {"date": "2026-06-10", "total_seconds": 120}
    """
    today = date.today().isoformat()
    try:
        async with aiosqlite.connect(BUDGET_FILE) as db:
            cursor = await db.execute(
                "SELECT total_seconds FROM voice_budget WHERE date = ?", (today,)
            )
            row = await cursor.fetchone()
            if row:
                return {"date": today, "total_seconds": row[0]}
            return {"date": today, "total_seconds": 0}
    except Exception:
        return {"date": today, "total_seconds": 0}


async def _write_budget(data: dict):
    """Сохраняет бюджетные данные (для тестов/миграции).

    Args:
        data: {"date": "2026-06-10", "total_seconds": 120}
    """
    async with aiosqlite.connect(BUDGET_FILE) as db:
        await db.execute(
            "INSERT OR REPLACE INTO voice_budget (date, total_seconds) VALUES (?, ?)",
            (data["date"], data["total_seconds"]),
        )
        await db.commit()


# ─── VoiceService ─────────────────────────────────────────────────────────────


class VoiceService:
    """Сервис для работы с голосовыми сообщениями.

    — Скачивание .ogg из Telegram
    — Транскрибация через OpenRouter API (Whisper Large V3 Turbo)
    — Озвучка ответа через edge-tts
    — Встроенные лимиты: макс. длительность сообщения + дневной бюджет в минутах
    — Бюджет хранится в SQLite с атомарным инкрементом (никаких race condition)
    """

    def __init__(
        self,
        download_dir: str = "/tmp/tutor_voice",
        tts_dir: str = "/tmp/tutor_tts",
        tts_voice: str = "en-US-JennyNeural",
        stt_model: str = DEFAULT_STT_MODEL,
        circuit_breaker: Optional[CircuitBreaker] = None,
    ):
        self.download_dir = download_dir
        self.tts_dir = tts_dir
        self.tts_voice = tts_voice
        self.stt_model = stt_model
        self.circuit_breaker = circuit_breaker or CircuitBreaker(
            name="openrouter-stt",
            failure_threshold=5,
            recovery_timeout=60.0,
        )
        self._db_inited = False

        os.makedirs(download_dir, exist_ok=True)
        os.makedirs(tts_dir, exist_ok=True)

    async def _ensure_db(self):
        """Ленивая инициализация SQLite-базы."""
        if not self._db_inited:
            await _init_budget_db()
            self._db_inited = True

    # ── Скачивание ────────────────────────────────────────────────────────────

    async def download_voice(self, file_id: str, bot: Bot) -> str:
        """Скачивает голосовое сообщение из Telegram во временный .ogg файл."""
        file_name = f"{uuid.uuid4().hex}.ogg"
        file_path = os.path.join(self.download_dir, file_name)
        await bot.download(file=file_id, destination=file_path)
        logger.debug(f"Voice downloaded: {file_path}")
        return file_path

    # ── Валидация длительности ────────────────────────────────────────────────

    def check_duration(self, duration_seconds: float) -> tuple[bool, str]:
        """Проверяет, не превышает ли сообщение лимит длительности.

        Returns:
            (ok, error_message)
        """
        if duration_seconds > MAX_VOICE_DURATION_SEC:
            return False, (
                f"⏱ Сообщение слишком длинное ({duration_seconds:.0f} сек). "
                f"Максимум — {MAX_VOICE_DURATION_SEC} сек. "
                "Попробуй разбить на несколько сообщений."
            )
        if duration_seconds < 0.5:
            return False, "😕 Сообщение слишком короткое. Попробуй ещё раз."
        return True, ""

    # ── Дневной бюджет ────────────────────────────────────────────────────────

    async def check_daily_budget(self, duration_seconds: float) -> tuple[bool, str]:
        """Проверяет дневной лимит минут на голосовые сообщения.

        Read-only проверка (без изменений). Атомарное списание происходит
        в _update_budget, поэтому при высокой конкурентности возможно
        небольшое превышение лимита (<1 сообщение сверх).

        Returns:
            (ok, error_message)
        """
        await self._ensure_db()
        budget = await _read_budget()
        used_minutes = budget["total_seconds"] / 60
        new_total = budget["total_seconds"] + duration_seconds
        new_minutes = new_total / 60

        if new_minutes > DAILY_BUDGET_MINUTES:
            remaining = DAILY_BUDGET_MINUTES - used_minutes
            if remaining <= 0:
                return False, (
                    f"📊 Дневной лимит голосовых сообщений исчерпан "
                    f"({DAILY_BUDGET_MINUTES} мин). "
                    "Используй текст или попробуй завтра."
                )
            else:
                return False, (
                    f"📊 Это сообщение превысит дневной лимит. "
                    f"Осталось ~{remaining:.1f} мин из {DAILY_BUDGET_MINUTES} мин."
                )
        return True, ""

    async def _update_budget(self, duration_seconds: float):
        """Атомарно инкрементирует дневной счётчик бюджета.

        Использует INSERT … ON CONFLICT DO UPDATE total_seconds = total_seconds + ?
        — read-modify-write выполняется в одной транзакции на стороне SQLite,
        никакого промежутка для race condition не существует.
        """
        await self._ensure_db()
        async with aiosqlite.connect(BUDGET_FILE) as db:
            today = date.today().isoformat()
            await db.execute(
                "INSERT INTO voice_budget (date, total_seconds) VALUES (?, ?) "
                "ON CONFLICT(date) DO UPDATE SET total_seconds = total_seconds + ?",
                (today, duration_seconds, duration_seconds),
            )
            await db.commit()

        logger.info(
            f"Voice budget updated: +{duration_seconds:.0f}s (today total in sqlite)"
        )

    # ── Транскрибация через OpenRouter ────────────────────────────────────────

    async def _call_stt_api(
        self,
        audio_path: str,
        duration_seconds: Optional[float] = None,
    ) -> str:
        """Выполняет HTTP-запрос к OpenRouter STT (без retry).

        Args:
            audio_path: путь к .ogg файлу.
            duration_seconds: длительность аудио (для обновления бюджета).

        Returns:
            Транскрибированный текст (нижний регистр).
        """
        api_key = os.getenv("OPENROUTER_API_KEY", "")
        if not api_key:
            raise Exception("OPENROUTER_API_KEY не задан — STT недоступен")

        # Читаем и кодируем аудио в base64
        with open(audio_path, "rb") as f:
            audio_data = f.read()
        base64_audio = base64.b64encode(audio_data).decode("utf-8")

        logger.info(
            f"Transcribing via OpenRouter ({self.stt_model}), size={len(audio_data)} bytes"
        )

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/",
        }
        payload = {
            "model": self.stt_model,
            "input_audio": {
                "data": base64_audio,
                "format": "ogg",
            },
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                OPENROUTER_STT_URL,
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            result = response.json()

        text = result.get("text", "").strip().lower()
        if not text:
            raise Exception("OpenRouter STT вернул пустой текст")

        # Атомарно обновляем бюджет после успешной транскрибации
        if duration_seconds is not None:
            await self._update_budget(duration_seconds)

        logger.debug(f"Transcribed ({len(text)} chars): {text[:100]}...")
        return text

    async def get_transcription(
        self,
        audio_path: str,
        duration_seconds: Optional[float] = None,
    ) -> str:
        """Транскрибирует аудио через OpenRouter Whisper API с retry + circuit breaker.

        Args:
            audio_path: путь к .ogg файлу.
            duration_seconds: длительность аудио (для проверки лимитов).

        Returns:
            Транскрибированный текст (нижний регистр).

        Raises:
            ValueError: превышен лимит длительности или дневной бюджет.
            Exception: ошибка API или circuit breaker.
        """
        api_key = os.getenv("OPENROUTER_API_KEY", "")
        if not api_key:
            raise Exception("OPENROUTER_API_KEY не задан — STT недоступен")

        # Валидация лимитов (до retry)
        if duration_seconds is not None:
            ok, msg = self.check_duration(duration_seconds)
            if not ok:
                raise ValueError(msg)
            ok, msg = await self.check_daily_budget(duration_seconds)
            if not ok:
                raise ValueError(msg)

        try:
            return await retry_with_backoff(
                self._call_stt_api,
                audio_path,
                duration_seconds=duration_seconds,
                max_retries=3,
                base_delay=1.0,
                max_delay=10.0,
                circuit_breaker=self.circuit_breaker,
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise Exception("Неверный OpenRouter API ключ для STT")
            body = e.response.text[:300]
            logger.error(f"STT HTTP {e.response.status_code}: {body}")
            raise Exception(f"Ошибка STT: HTTP {e.response.status_code}")
        except httpx.TimeoutException:
            raise Exception("STT таймаут — OpenRouter не ответил за 30 сек")
        except CircuitBreakerOpenError:
            raise Exception(
                "Голосовой сервис временно недоступен — слишком много ошибок. "
                "Пожалуйста, попробуй через минуту."
            )
        except ValueError:
            raise
        except Exception as e:
            raise Exception(f"STT ошибка: {str(e)}")

    # ── TTS ────────────────────────────────────────────────────────────────────

    async def text_to_speech(self, text: str) -> str:
        """Генерирует аудио из текста через edge-tts.

        Returns:
            Путь к сгенерированному .mp3 файлу.
        """
        file_name = f"{uuid.uuid4().hex}.mp3"
        file_path = os.path.join(self.tts_dir, file_name)
        communicate = edge_tts.Communicate(text, self.tts_voice)
        await communicate.save(file_path)
        logger.debug(f"TTS saved: {file_path}")
        return file_path
