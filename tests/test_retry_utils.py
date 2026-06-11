"""Тесты для retry_utils — CircuitBreaker, retry_with_backoff, is_retryable."""

import asyncio
import pytest

from bot.services.retry_utils import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    CircuitState,
    is_retryable,
    retry_with_backoff,
)


# ═══════════════════════════════════════════════════════════════════════════════
# CircuitBreaker
# ═══════════════════════════════════════════════════════════════════════════════


class TestCircuitBreaker:
    """Проверка состояний и переходов circuit breaker."""

    async def test_initial_state_closed(self):
        """Сразу после создания — CLOSED."""
        cb = CircuitBreaker(name="test", failure_threshold=3)
        assert cb.state == CircuitState.CLOSED
        assert await cb.can_call() is True

    async def test_opens_after_threshold_failures(self):
        """После N ошибок — OPEN, запросы блокируются."""
        cb = CircuitBreaker(name="test", failure_threshold=3)
        for _ in range(3):
            assert await cb.can_call() is True
            await cb.on_failure()

        assert cb.state == CircuitState.OPEN
        assert await cb.can_call() is False

    async def test_does_not_open_below_threshold(self):
        """Меньше N ошибок — цепь остаётся закрытой."""
        cb = CircuitBreaker(name="test", failure_threshold=3)
        for _ in range(2):
            await cb.on_failure()
        assert cb.state == CircuitState.CLOSED
        assert await cb.can_call() is True

    async def test_success_resets_failure_count(self):
        """Успех сбрасывает счётчик ошибок."""
        cb = CircuitBreaker(name="test", failure_threshold=2)
        await cb.on_failure()
        await cb.on_success()  # сброс
        await cb.on_failure()
        assert cb.state == CircuitState.CLOSED  # ещё не порог
        await cb.on_failure()
        assert cb.state == CircuitState.OPEN  # теперь порог

    async def test_recovery_to_half_open(self):
        """Через recovery_timeout цепь становится HALF_OPEN."""
        cb = CircuitBreaker(
            name="test",
            failure_threshold=2,
            recovery_timeout=0.05,  # 50 мс
        )
        await cb.on_failure()
        await cb.on_failure()
        assert cb.state == CircuitState.OPEN

        await asyncio.sleep(0.06)
        assert await cb.can_call() is True
        assert cb.state == CircuitState.HALF_OPEN

    async def test_half_open_success_closes_circuit(self):
        """Успех в HALF_OPEN переводит в CLOSED."""
        cb = CircuitBreaker(
            name="test",
            failure_threshold=2,
            recovery_timeout=0.05,
        )
        await cb.on_failure()
        await cb.on_failure()
        assert cb.state == CircuitState.OPEN

        await asyncio.sleep(0.06)
        assert await cb.can_call() is True  # HALF_OPEN

        await cb.on_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    async def test_half_open_failure_reopens(self):
        """Неудача в HALF_OPEN снова переводит в OPEN."""
        cb = CircuitBreaker(
            name="test",
            failure_threshold=2,
            recovery_timeout=0.05,
        )
        await cb.on_failure()
        await cb.on_failure()
        assert cb.state == CircuitState.OPEN

        await asyncio.sleep(0.06)
        await cb.can_call()  # → HALF_OPEN
        await cb.on_failure()

        assert cb.state == CircuitState.OPEN
        assert await cb.can_call() is False

    async def test_half_open_limits_requests(self):
        """В HALF_OPEN пропускается только half_open_max_requests запросов."""
        cb = CircuitBreaker(
            name="test",
            failure_threshold=2,
            recovery_timeout=0.05,
            half_open_max_requests=2,
        )
        await cb.on_failure()
        await cb.on_failure()

        await asyncio.sleep(0.06)
        # Должно пропустить 2 запроса
        assert await cb.can_call() is True
        assert await cb.can_call() is True
        # Третий — заблокирован (ещё не было success/failure)
        assert await cb.can_call() is False

    async def test_force_open(self):
        """force_open принудительно размыкает цепь."""
        cb = CircuitBreaker(name="test", failure_threshold=5)
        await cb.force_open()
        assert cb.state == CircuitState.OPEN
        assert cb.failure_count == 5
        assert await cb.can_call() is False


# ═══════════════════════════════════════════════════════════════════════════════
# is_retryable
# ═══════════════════════════════════════════════════════════════════════════════


class TestIsRetryable:
    """Проверка определения повторяемости ошибок."""

    def test_timeout_is_retryable(self):
        assert is_retryable(TimeoutError("Connection timeout"))

    def test_500_is_retryable(self):
        assert is_retryable(Exception("HTTP 500 Internal Server Error"))

    def test_429_is_retryable(self):
        assert is_retryable(Exception("429 Too Many Requests"))

    def test_connection_error_is_retryable(self):
        assert is_retryable(ConnectionError("Connection refused"))
        assert is_retryable(ConnectionResetError("Connection reset by peer"))

    def test_service_unavailable_is_retryable(self):
        assert is_retryable(Exception("503 Service Unavailable"))

    def test_401_is_not_retryable(self):
        assert not is_retryable(Exception("HTTP 401 Unauthorized"))

    def test_403_is_not_retryable(self):
        assert not is_retryable(Exception("403 Forbidden"))

    def test_invalid_api_key_is_not_retryable(self):
        assert not is_retryable(Exception("Invalid API key"))

    def test_nevernyj_api_key_is_not_retryable(self):
        assert not is_retryable(Exception("Неверный API ключ"))

    def test_empty_message_returns_false(self):
        assert not is_retryable(Exception(""))

    def test_generic_error_returns_false(self):
        assert not is_retryable(Exception("Something went wrong"))


# ═══════════════════════════════════════════════════════════════════════════════
# retry_with_backoff
# ═══════════════════════════════════════════════════════════════════════════════


class TestRetryWithBackoff:
    """Проверка логики retry-механизма."""

    async def test_success_on_first_attempt(self):
        """Если функция выполнилась успешно с первого раза — возвращаем результат."""

        async def ok():
            return "done"

        result = await retry_with_backoff(ok, max_retries=3)
        assert result == "done"

    async def test_retries_and_succeeds(self):
        """Два отказа, потом успех."""
        call_count = 0

        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Connection refused")
            return "OK"

        result = await retry_with_backoff(
            flaky,
            max_retries=3,
            base_delay=0.01,
        )
        assert result == "OK"
        assert call_count == 3

    async def test_exhausts_retries_and_raises(self):
        """После N попыток выбрасывает последнее исключение."""

        async def always_fail():
            raise ConnectionError("Always fails")

        with pytest.raises(ConnectionError, match="Always fails"):
            await retry_with_backoff(
                always_fail,
                max_retries=2,
                base_delay=0.01,
            )

    async def test_non_retryable_error_raises_immediately(self):
        """Неповторяемая ошибка вылетает сразу, без retry."""
        call_count = 0

        async def auth_fail():
            nonlocal call_count
            call_count += 1
            raise Exception("401 Unauthorized")

        with pytest.raises(Exception, match="401 Unauthorized"):
            await retry_with_backoff(
                auth_fail,
                max_retries=3,
                base_delay=0.01,
            )
        assert call_count == 1  # только один вызов

    async def test_custom_retryable_check(self):
        """Кастомная функция проверки повторяемости."""

        async def custom_fail():
            raise Exception("custom")

        with pytest.raises(Exception, match="custom"):
            await retry_with_backoff(
                custom_fail,
                max_retries=2,
                base_delay=0.01,
                retryable_check=lambda e: False,  # никогда не повторяем
            )

    async def test_circuit_breaker_blocks_request(self):
        """Если circuit breaker OPEN — retry выбрасывает CircuitBreakerOpenError
        без вызова функции."""
        cb = CircuitBreaker(name="test", failure_threshold=2)
        await cb.on_failure()
        await cb.on_failure()
        assert cb.state == CircuitState.OPEN

        async def never_called():
            pytest.fail("Этот вызов не должен произойти")

        with pytest.raises(CircuitBreakerOpenError):
            await retry_with_backoff(
                never_called,
                max_retries=2,
                circuit_breaker=cb,
            )

    async def test_circuit_breaker_recovers_on_success(self):
        """После успеха circuit breaker закрывается."""
        cb = CircuitBreaker(name="test", failure_threshold=2)
        await cb.on_failure()
        await cb.on_failure()
        assert cb.state == CircuitState.OPEN

        # Симулируем timeout recovery
        cb._last_failure_time = 0
        await cb._check_open_timeout()
        assert cb.state == CircuitState.HALF_OPEN

        async def ok():
            return "recovered"

        result = await retry_with_backoff(ok, circuit_breaker=cb)
        assert result == "recovered"
        assert cb.state == CircuitState.CLOSED


# ═══════════════════════════════════════════════════════════════════════════════
# Интеграция с реальным AI-сервисом (проверка, что моки не сломались)
# ═══════════════════════════════════════════════════════════════════════════════


class TestAiIntegration:
    """Проверка, что AITutor с circuit breaker по-прежнему работает для моков."""

    async def test_mock_response_still_works(self):
        """Тестовый ключ 'test_key' не трогает circuit breaker."""
        from bot.services.ai_service import AITutor

        tutor = AITutor(level="A1", api_key="test_key", topic="introduction")
        result = await tutor.chat("hello")
        assert result["reply"] is not None
        assert "corrections" in result
        assert result["rating"] == 4

    async def test_mock_with_corrections(self):
        """Моковые исправления работают с новым AITutor."""
        from bot.services.ai_service import AITutor

        tutor = AITutor(level="B1", api_key="test_key")
        result = await tutor.chat("I go to the store yesterday")
        assert len(result["corrections"]) > 0
        assert any("I go" in c["original"] for c in result["corrections"])

    async def test_custom_circuit_breaker_injection(self):
        """Можно передать свой circuit breaker в AITutor."""
        from bot.services.ai_service import AITutor

        cb = CircuitBreaker(name="custom-chat")
        tutor = AITutor(level="A2", api_key="test_key", circuit_breaker=cb)
        assert tutor.circuit_breaker is cb
        assert tutor.circuit_breaker.name == "custom-chat"

    async def test_voice_service_circuit_breaker_injection(self):
        """Можно передать свой circuit breaker в VoiceService."""
        from bot.services.voice_service import VoiceService

        cb = CircuitBreaker(name="custom-stt")
        svc = VoiceService(circuit_breaker=cb)
        assert svc.circuit_breaker is cb
        assert svc.circuit_breaker.name == "custom-stt"
