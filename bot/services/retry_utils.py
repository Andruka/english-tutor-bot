"""Retry + Circuit Breaker для внешних API (OpenRouter)."""

import asyncio
import random
import time
import logging
from typing import Callable, Awaitable, Optional

logger = logging.getLogger(__name__)


# ─── Типы состояний Circuit Breaker ──────────────────────────────────────────


class CircuitState:
    CLOSED = "CLOSED"  # Нормальная работа
    OPEN = "OPEN"  # Отказ — запросы блокируются
    HALF_OPEN = "HALF_OPEN"  # Пробный пропуск после таймаута


# ─── Circuit Breaker ─────────────────────────────────────────────────────────


class CircuitBreaker:
    """Защищает внешний API от каскадных сбоев.

    Состояния:
        CLOSED   — нормальная работа, ошибки считаются.
        OPEN     — после N ошибок запросы блокируются на recovery_timeout.
        HALF_OPEN — после таймаута пропускается тестовый запрос.
          Если успешен → CLOSED. Если сбой → OPEN.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max_requests: int = 1,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_requests = half_open_max_requests

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._half_open_requests = 0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> str:
        return self._state

    @property
    def failure_count(self) -> int:
        return self._failure_count

    async def _check_open_timeout(self):
        """Если прошло достаточно времени, переходим в HALF_OPEN."""
        if self._state != CircuitState.OPEN:
            return
        elapsed = time.monotonic() - self._last_failure_time
        if elapsed >= self.recovery_timeout:
            self._state = CircuitState.HALF_OPEN
            self._half_open_requests = 0
            logger.info(
                "Circuit [%s] → HALF_OPEN after %.1fs recovery",
                self.name,
                elapsed,
            )

    async def can_call(self) -> bool:
        """Можно ли сейчас выполнять запрос? Возвращает True/False."""
        async with self._lock:
            if self._state == CircuitState.CLOSED:
                return True

            if self._state == CircuitState.OPEN:
                await self._check_open_timeout()
                if self._state == CircuitState.HALF_OPEN:
                    self._half_open_requests += 1
                    return True
                return False

            # HALF_OPEN — пропускаем лимитированное число запросов
            if self._half_open_requests < self.half_open_max_requests:
                self._half_open_requests += 1
                return True
            return False

    async def on_success(self):
        """Успешный запрос — сбрасываем счётчик ошибок, закрываем цепь."""
        async with self._lock:
            self._failure_count = 0
            self._half_open_requests = 0
            if self._state != CircuitState.CLOSED:
                self._state = CircuitState.CLOSED
                logger.info("Circuit [%s] → CLOSED (recovered)", self.name)

    async def on_failure(self):
        """Ошибка — инкрементируем счётчик, открываем цепь при пороге."""
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()
            if self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                logger.warning(
                    "Circuit [%s] → OPEN after %d failures",
                    self.name,
                    self._failure_count,
                )

    async def force_open(self):
        """Принудительно открыть цепь (для тестов/админки)."""
        async with self._lock:
            self._state = CircuitState.OPEN
            self._failure_count = self.failure_threshold
            self._last_failure_time = time.monotonic()


class CircuitBreakerOpenError(Exception):
    """Вызывается, когда circuit breaker блокирует запрос."""

    pass


# ─── Проверка повторяемости ошибок ──────────────────────────────────────────

DEFAULT_RETRYABLE_MESSAGES = [
    "timeout",
    "таймаут",
    "500",
    "502",
    "503",
    "504",
    "5",
    "rate limit",
    "429",
    "connection",
    "connection refused",
    "connection reset",
    "eof",
    "broken pipe",
    "temporarily unavailable",
    "service unavailable",
    "bad gateway",
    "gateway timeout",
    "too many requests",
]

DEFAULT_NON_RETRYABLE_MESSAGES = [
    "401",
    "403",
    "invalid api key",
    "api_key",
    "неверный",
    "недоступен",
]


def is_retryable(exception: Exception) -> bool:
    """Определяет, можно ли повторить операцию при данной ошибке.

    Не повторяем: 401, 403, invalid api key, ошибки конфигурации.
    Повторяем: таймауты, 5xx, 429, connection errors.
    """
    msg = str(exception).lower()

    for pattern in DEFAULT_NON_RETRYABLE_MESSAGES:
        if pattern in msg:
            return False

    for pattern in DEFAULT_RETRYABLE_MESSAGES:
        if pattern in msg:
            return True

    return False


# ─── Retry with Exponential Backoff ──────────────────────────────────────────


async def retry_with_backoff(
    func: Callable[..., Awaitable],
    *args,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 10.0,
    retryable_check: Optional[Callable[[Exception], bool]] = None,
    circuit_breaker: Optional[CircuitBreaker] = None,
    **kwargs,
):
    """Выполняет асинхронную функцию с retry + exponential backoff + jitter.

    Args:
        func: асинхронная функция.
        max_retries: макс. число повторных попыток (всего = 1 + max_retries).
        base_delay: начальная задержка (сек), удваивается с каждой попыткой.
        max_delay: макс. задержка (сек).
        retryable_check: кастомная функция проверки повторяемости ошибки.
        circuit_breaker: опциональный CircuitBreaker.

    Raises:
        CircuitBreakerOpenError: цепь разомкнута.
        Последнее исключение от func, если все попытки исчерпаны.
    """
    if retryable_check is None:
        retryable_check = is_retryable

    for attempt in range(max_retries + 1):
        if circuit_breaker:
            can = await circuit_breaker.can_call()
            if not can:
                raise CircuitBreakerOpenError(
                    f"Circuit [{circuit_breaker.name}] открыт "
                    f"(state={circuit_breaker.state}, "
                    f"failures={circuit_breaker.failure_count}) — "
                    f"запрос заблокирован."
                )

        try:
            result = await func(*args, **kwargs)
            if circuit_breaker:
                await circuit_breaker.on_success()
            return result
        except CircuitBreakerOpenError:
            raise  # не оборачиваем
        except Exception as e:
            if circuit_breaker:
                await circuit_breaker.on_failure()

            if attempt < max_retries and retryable_check(e):
                delay = min(base_delay * (2**attempt), max_delay)
                jitter = delay * (0.75 + random.random() * 0.5)
                logger.warning(
                    "Retry %d/%d failed: %s. Retrying in %.1fs...",
                    attempt + 1,
                    max_retries + 1,
                    e,
                    jitter,
                )
                await asyncio.sleep(jitter)
            else:
                raise
