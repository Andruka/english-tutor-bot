"""Тесты VoiceService — лимиты, бюджет (SQLite), OpenRouter транскрибация."""

import pytest
import os
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import date


# =============================================================================
# check_duration
# =============================================================================


class TestCheckDuration:
    """Проверка длительности голосового сообщения."""

    @pytest.fixture
    def service(self):
        from bot.services.voice_service import VoiceService

        return VoiceService()

    def test_normal_duration(self, service):
        """30 секунд — нормально."""
        ok, msg = service.check_duration(30.0)
        assert ok is True
        assert msg == ""

    def test_exactly_max(self, service):
        """Ровно 60 секунд — ок."""
        ok, msg = service.check_duration(60.0)
        assert ok is True
        assert msg == ""

    def test_too_long(self, service):
        """61 секунда — превышение."""
        ok, msg = service.check_duration(61.0)
        assert ok is False
        assert "слишком длинное" in msg
        assert "61" in msg

    def test_too_short(self, service):
        """0.1 секунды — слишком коротко."""
        ok, msg = service.check_duration(0.1)
        assert ok is False
        assert "короткое" in msg

    def test_exactly_min(self, service):
        """Ровно 0.5 секунды — ок."""
        ok, msg = service.check_duration(0.5)
        assert ok is True
        assert msg == ""


# =============================================================================
# check_daily_budget
# =============================================================================


class TestCheckDailyBudget:
    """Проверка дневного бюджета голосовых сообщений (SQLite)."""

    @pytest.fixture(autouse=True)
    async def setup(self, tmp_path):
        import bot.services.voice_service as vs

        self._orig_file = vs.BUDGET_FILE
        self._test_file = str(tmp_path / "voice_budget.db")
        vs.BUDGET_FILE = self._test_file
        vs.DAILY_BUDGET_MINUTES = 30
        await vs._init_budget_db()
        yield
        vs.BUDGET_FILE = self._orig_file

    @pytest.fixture
    def service(self):
        from bot.services.voice_service import VoiceService

        return VoiceService()

    async def test_fresh_budget(self, service):
        """Пустой бюджет — всё ок."""
        ok, msg = await service.check_daily_budget(30.0)
        assert ok is True
        assert msg == ""

    async def test_under_budget(self, service):
        """5 минут использовано, ещё 10 — ок."""
        from bot.services.voice_service import _write_budget

        today = date.today().isoformat()
        await _write_budget({"date": today, "total_seconds": 300})
        ok, msg = await service.check_daily_budget(600)
        assert ok is True

    async def test_exactly_at_budget(self, service):
        """29 мин использовано, ещё 1 мин — ровно лимит."""
        from bot.services.voice_service import _write_budget

        today = date.today().isoformat()
        await _write_budget({"date": today, "total_seconds": 1740})  # 29 min
        ok, msg = await service.check_daily_budget(60)  # 1 min
        assert ok is True

    async def test_exceeds_budget(self, service):
        """29 мин использовано, ещё 2 мин — превышение."""
        from bot.services.voice_service import _write_budget

        today = date.today().isoformat()
        await _write_budget({"date": today, "total_seconds": 1740})
        ok, msg = await service.check_daily_budget(120)
        assert ok is False
        assert "превысит" in msg or "лимит" in msg

    async def test_budget_exhausted(self, service):
        """30 мин уже использовано — лимит исчерпан."""
        from bot.services.voice_service import _write_budget

        today = date.today().isoformat()
        await _write_budget({"date": today, "total_seconds": 1800})
        ok, msg = await service.check_daily_budget(10)
        assert ok is False
        assert "исчерпан" in msg


# =============================================================================
# Budget file read/write (SQLite persistence)
# =============================================================================


class TestBudgetPersistence:
    """Чтение и запись бюджета через SQLite."""

    @pytest.fixture(autouse=True)
    async def setup(self, tmp_path):
        import bot.services.voice_service as vs

        self._orig_file = vs.BUDGET_FILE
        self._test_file = str(tmp_path / "voice_budget.db")
        vs.BUDGET_FILE = self._test_file
        await vs._init_budget_db()
        yield
        vs.BUDGET_FILE = self._orig_file

    async def test_read_no_file(self):
        """Нет данных — возвращает сегодня с 0."""
        from bot.services.voice_service import _read_budget

        data = await _read_budget()
        assert data["date"] == date.today().isoformat()
        assert data["total_seconds"] == 0

    async def test_read_today_data(self):
        """Запись с сегодняшней датой — возвращает сохранённые значения."""
        from bot.services.voice_service import _read_budget, _write_budget

        today = date.today().isoformat()
        await _write_budget({"date": today, "total_seconds": 500})
        data = await _read_budget()
        assert data["total_seconds"] == 500

    async def test_read_old_date_resets(self):
        """Запись со старой датой — не видна, возвращает 0."""
        from bot.services.voice_service import _read_budget, _write_budget

        yesterday = "2020-01-01"
        await _write_budget({"date": yesterday, "total_seconds": 9999})
        data = await _read_budget()
        assert data["date"] == date.today().isoformat()
        assert data["total_seconds"] == 0

    async def test_write_and_read_back(self):
        """Записали — прочитали то же самое."""
        from bot.services.voice_service import _read_budget, _write_budget

        await _write_budget({"date": date.today().isoformat(), "total_seconds": 123})
        data = await _read_budget()
        assert data["total_seconds"] == 123

    async def test_update_budget(self):
        """_update_budget атомарно добавляет секунды к счётчику."""
        from bot.services.voice_service import _read_budget
        from bot.services.voice_service import VoiceService

        service = VoiceService()
        await service._update_budget(42)
        data = await _read_budget()
        assert data["total_seconds"] == 42


# =============================================================================
# get_transcription (OpenRouter)
# =============================================================================


class TestGetTranscription:
    """Транскрибация через OpenRouter API."""

    @pytest.fixture(autouse=True)
    async def setup(self, tmp_path):
        import bot.services.voice_service as vs

        self._orig_file = vs.BUDGET_FILE
        self._test_file = str(tmp_path / "voice_budget.db")
        vs.BUDGET_FILE = self._test_file
        await vs._init_budget_db()
        yield
        vs.BUDGET_FILE = self._orig_file

    @pytest.fixture
    def service(self):
        from bot.services.voice_service import VoiceService

        return VoiceService()

    @pytest.fixture
    def test_audio(self, tmp_path):
        """Создаёт минимальный .ogg файл для тестов."""
        path = str(tmp_path / "test.ogg")
        with open(path, "wb") as f:
            f.write(b"OggS\x00\x02\x00\x00\x00\x00\x00\x00\x00\x00FAKE")
        return path

    async def test_successful_transcription(self, service, test_audio):
        """Успешная транскрибация возвращает текст в нижнем регистре."""
        with patch("bot.services.voice_service.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.json.return_value = {"text": "Hello World Test"}
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__.return_value = mock_client
            mock_client_cls.return_value = mock_client

            with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-...5678"}):
                text = await service.get_transcription(test_audio)

        assert text == "hello world test"

    async def test_missing_api_key(self, service, test_audio):
        """Без API ключа — Exception."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(Exception, match="OPENROUTER_API_KEY не задан"):
                await service.get_transcription(test_audio)

    async def test_duration_check_called(self, service, test_audio):
        """Переданная длительность проверяется."""
        with patch.object(
            service, "check_duration", return_value=(False, "слишком длинное")
        ):
            with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-...5678"}):
                with pytest.raises(ValueError, match="слишком длинное"):
                    await service.get_transcription(test_audio, duration_seconds=120.0)

    async def test_budget_check_called(self, service, test_audio):
        """Переданная длительность проверяется по бюджету."""
        with patch.object(service, "check_duration", return_value=(True, "")):
            with patch.object(
                service, "check_daily_budget", return_value=(False, "лимит исчерпан")
            ):
                with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-...5678"}):
                    with pytest.raises(ValueError, match="лимит исчерпан"):
                        await service.get_transcription(
                            test_audio, duration_seconds=10.0
                        )

    async def test_http_401(self, service, test_audio):
        """401 ошибка — неверный ключ."""
        with patch("bot.services.voice_service.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            resp = MagicMock()
            resp.status_code = 401
            resp.text = "Unauthorized"
            from httpx import HTTPStatusError, Request

            resp.raise_for_status.side_effect = HTTPStatusError(
                "401", request=MagicMock(spec=Request), response=resp
            )
            mock_client.post = AsyncMock(side_effect=resp.raise_for_status.side_effect)
            mock_client.__aenter__.return_value = mock_client
            mock_client_cls.return_value = mock_client

            with patch.dict(os.environ, {"OPENROUTER_API_KEY": "***"}):
                with pytest.raises(Exception, match="Неверный OpenRouter API ключ"):
                    await service.get_transcription(test_audio)

    async def test_http_timeout(self, service, test_audio):
        """Таймаут — понятное сообщение."""
        from httpx import TimeoutException

        with patch("bot.services.voice_service.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=TimeoutException("timeout"))
            mock_client.__aenter__.return_value = mock_client
            mock_client_cls.return_value = mock_client

            with patch.dict(os.environ, {"OPENROUTER_API_KEY": "***"}):
                with pytest.raises(Exception, match="таймаут"):
                    await service.get_transcription(test_audio)

    async def test_empty_response(self, service, test_audio):
        """API вернул пустой текст — Exception."""
        with patch("bot.services.voice_service.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.json.return_value = {"text": ""}
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__.return_value = mock_client
            mock_client_cls.return_value = mock_client

            with patch.dict(os.environ, {"OPENROUTER_API_KEY": "***"}):
                with pytest.raises(Exception, match="пустой текст"):
                    await service.get_transcription(test_audio)

    async def test_budget_updated_on_success(self, service, test_audio):
        """После успешной транскрибации бюджет обновляется."""
        from bot.services.voice_service import _read_budget

        with patch("bot.services.voice_service.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.json.return_value = {"text": "hello world"}
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__.return_value = mock_client
            mock_client_cls.return_value = mock_client

            with patch.dict(os.environ, {"OPENROUTER_API_KEY": "***"}):
                await service.get_transcription(test_audio, duration_seconds=30.0)

            data = await _read_budget()
            assert data["total_seconds"] == 30


# =============================================================================
# download_voice + text_to_speech (unchanged API)
# =============================================================================


class TestDownloadVoice:
    """Скачивание голосового сообщения (API не изменился)."""

    async def test_returns_path(self):
        from bot.services.voice_service import VoiceService

        mock_bot = AsyncMock()
        mock_bot.download = AsyncMock()
        service = VoiceService(download_dir="/tmp/test_voice")
        result = await service.download_voice("file_id", mock_bot)
        assert isinstance(result, str)
        assert result.startswith("/tmp/test_voice/")
        assert result.endswith(".ogg")

    async def test_calls_bot_download(self):
        from bot.services.voice_service import VoiceService

        mock_bot = AsyncMock()
        mock_bot.download = AsyncMock()
        service = VoiceService(download_dir="/tmp/test_voice")
        await service.download_voice("file_123", mock_bot)
        mock_bot.download.assert_awaited_once()


class TestTextToSpeech:
    """Озвучка текста (API не изменился)."""

    async def test_returns_path(self):
        from bot.services.voice_service import VoiceService

        mock_comm = MagicMock()
        mock_comm.save = AsyncMock()
        with patch(
            "bot.services.voice_service.edge_tts.Communicate", return_value=mock_comm
        ):
            service = VoiceService(tts_dir="/tmp/test_tts")
            result = await service.text_to_speech("Hello")
        assert isinstance(result, str)
        assert result.startswith("/tmp/test_tts/")

    async def test_short_text(self):
        from bot.services.voice_service import VoiceService

        mock_comm = MagicMock()
        mock_comm.save = AsyncMock()
        with patch(
            "bot.services.voice_service.edge_tts.Communicate", return_value=mock_comm
        ):
            service = VoiceService(tts_dir="/tmp/test_tts")
            result = await service.text_to_speech("Hi")
        assert isinstance(result, str)
