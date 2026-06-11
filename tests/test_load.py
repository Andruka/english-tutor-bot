"""Нагрузочные тесты VoiceService — производительность, race conditions, стабильность.

Сценарии:
  1. Конкурентный budget (SQLite атомарный инкремент — race condition исключён)
  2. Множественные check_duration / check_daily_budget
  3. Параллельная get_transcription с моком HTTP
  4. Полный цикл: скачивание → транскрибация → ответ
"""

import pytest
import os
import asyncio
import time
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from bot.services.voice_service import (
    VoiceService,
    _read_budget,
    _write_budget,
)


# =============================================================================
# Вспомогательные фикстуры
# =============================================================================


@pytest.fixture(autouse=True)
async def isolate_budget(tmp_path):
    """Каждый тест работает со своей SQLite-базой бюджета."""
    import bot.services.voice_service as vs

    _orig = vs.BUDGET_FILE
    vs.BUDGET_FILE = str(tmp_path / "voice_budget.db")
    await vs._init_budget_db()
    yield
    vs.BUDGET_FILE = _orig


@pytest.fixture
def service():
    return VoiceService()


# =============================================================================
# Тест 1: Race-condition бюджета под параллельной нагрузкой
# =============================================================================


@pytest.mark.slow
class TestBudgetRaceCondition:
    """Проверяет атомарность SQLite-инкремента при конкурентном доступе.

    Если 10 одновременных вызовов _update_budget по 30 сек каждый —
    с атомарным INSERT … ON CONFLICT DO UPDATE итог = 10 × 30 = 300 сек.
    """

    @pytest.mark.asyncio
    async def test_budget_no_race(self, service):
        """10 конкурентных _update_budget по 30 сек — должно накопиться 300 сек."""
        N_CONCURRENT = 10
        DURATION = 30.0

        async def update_budget():
            await service._update_budget(DURATION)

        start = time.perf_counter()
        await asyncio.gather(*[update_budget() for _ in range(N_CONCURRENT)])
        elapsed = time.perf_counter() - start

        data = await _read_budget()
        expected = N_CONCURRENT * DURATION

        print(f"\n  Budget atomic increment: {N_CONCURRENT} concurrent × {DURATION}s")
        print(f"  Time: {elapsed:.3f}s")
        print(f"  Expected: {expected:.0f}s, Got: {data['total_seconds']:.0f}s")
        print(f"  Loss: {expected - data['total_seconds']:.0f}s")

        # С атомарным инкрементом потерь быть не должно
        assert data["total_seconds"] == expected, (
            f"Race condition! Expected {expected}, got {data['total_seconds']}"
        )

    @pytest.mark.asyncio
    async def test_budget_high_contention(self, service):
        """50 конкурентных _update_budget — проверка стабильности."""
        N_CONCURRENT = 50
        DURATION = 5.0

        async def update_budget():
            await service._update_budget(DURATION)

        start = time.perf_counter()
        await asyncio.gather(*[update_budget() for _ in range(N_CONCURRENT)])
        elapsed = time.perf_counter() - start

        data = await _read_budget()
        expected = N_CONCURRENT * DURATION

        print(f"\n  High contention: {N_CONCURRENT} concurrent × {DURATION}s")
        print(f"  Time: {elapsed:.3f}s")
        print(f"  Expected: {expected:.0f}s, Got: {data['total_seconds']:.0f}s")

        assert data["total_seconds"] == expected, (
            f"Race! Expected {expected}, got {data['total_seconds']} "
            f"(lost {expected - data['total_seconds']:.0f}s)"
        )

    @pytest.mark.asyncio
    async def test_alternating_updates(self, service):
        """Чередующиеся вызовы с разными значениями — сумма должна сходиться."""
        calls = [1.5, 10.0, 3.0, 7.5, 20.0, 0.5, 15.0, 2.0, 30.0, 5.0]
        expected = sum(calls)

        async def update(val):
            await service._update_budget(val)

        await asyncio.gather(*[update(v) for v in calls])

        data = await _read_budget()

        print(f"\n  Alternating updates: {len(calls)} calls, sum={expected:.1f}s")
        print(f"  Got: {data['total_seconds']:.1f}s")

        assert abs(data["total_seconds"] - expected) < 0.01, (
            f"Sum mismatch: expected {expected}, got {data['total_seconds']}"
        )


# =============================================================================
# Тест 2: check_duration под нагрузкой
# =============================================================================


@pytest.mark.slow
class TestDurationLoad:
    """1000+ вызовов check_duration — замер времени."""

    @pytest.mark.asyncio
    async def test_duration_throughput(self, service):
        """1000 вызовов check_duration с разными значениями."""
        N = 1000
        durations = [i * 0.1 for i in range(N)]  # 0.1s .. 100s

        start = time.perf_counter()
        results = await asyncio.gather(
            *[asyncio.to_thread(service.check_duration, d) for d in durations]
        )
        elapsed = time.perf_counter() - start

        ok_count = sum(1 for ok, _ in results if ok)
        rejected_count = sum(1 for ok, _ in results if not ok)
        ops_per_sec = N / elapsed if elapsed > 0 else float("inf")

        print(f"\n  Duration: {N} calls in {elapsed:.3f}s ({ops_per_sec:.0f} ops/s)")
        print(f"  Accepted: {ok_count}, Rejected: {rejected_count}")

        assert ops_per_sec > 100  # хотя бы 100 ops/s
        assert ok_count > 0
        assert rejected_count > 0


# =============================================================================
# Тест 3: check_daily_budget под нагрузкой
# =============================================================================


@pytest.mark.slow
class TestBudgetCheckLoad:
    """Параллельные check_daily_budget — нет исключений, корректные результаты."""

    @pytest.mark.asyncio
    async def test_budget_check_parallel(self, service):
        """50 параллельных вызовов: 25 под лимитом, 25 над лимитом."""
        from bot.services.voice_service import DAILY_BUDGET_MINUTES

        limit_seconds = DAILY_BUDGET_MINUTES * 60  # 1800
        await _write_budget(
            {
                "date": date.today().isoformat(),
                "total_seconds": limit_seconds - 100,
            }
        )
        # -100s от лимита: 10s пройдёт, 200s — превысит

        N = 50
        durations = [10.0 if i % 2 == 0 else 200.0 for i in range(N)]

        async def check(d):
            return await service.check_daily_budget(d)

        start = time.perf_counter()
        results = await asyncio.gather(*[check(d) for d in durations])
        elapsed = time.perf_counter() - start

        ok_count = sum(1 for ok, _ in results if ok)
        rejected_count = sum(1 for ok, _ in results if not ok)
        ops_per_sec = N / elapsed if elapsed > 0 else float("inf")

        print(
            f"\n  Budget check: {N} calls in {elapsed:.3f}s ({ops_per_sec:.0f} ops/s)"
        )
        print(f"  Accepted: {ok_count}, Rejected: {rejected_count}")

        assert ok_count > 0
        assert rejected_count > 0
        assert ops_per_sec > 50


# =============================================================================
# Тест 4: get_transcription под нагрузкой (мок HTTP)
# =============================================================================


@pytest.mark.slow
class TestTranscriptionLoad:
    """Параллельные get_transcription с мокированным OpenRouter API."""

    @pytest.fixture
    def test_audio(self, tmp_path):
        path = str(tmp_path / "test.ogg")
        with open(path, "wb") as f:
            f.write(b"OggS\x00\x02\x00\x00\x00\x00\x00\x00\x00\x00FAKE")
        return path

    def _mock_httpx(self, delay: float = 0.05):
        """Создаёт мок httpx.AsyncClient с симулированной задержкой."""

        async def mock_post(url, **kwargs):
            await asyncio.sleep(delay)
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.json.return_value = {"text": "hello world test"}
            return mock_response

        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_client.__aenter__.return_value = mock_client
        mock_client_cls = MagicMock(return_value=mock_client)
        return mock_client_cls

    @pytest.mark.asyncio
    async def test_parallel_transcriptions(self, service, test_audio):
        """10 параллельных get_transcription с моком — замер времени."""
        N = 10
        mock_client_cls = self._mock_httpx(delay=0.05)

        with patch("bot.services.voice_service.httpx.AsyncClient", mock_client_cls):
            with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-xxx"}):
                start = time.perf_counter()
                tasks = [
                    service.get_transcription(test_audio, duration_seconds=5.0)
                    for _ in range(N)
                ]
                results = await asyncio.gather(*tasks)
                elapsed = time.perf_counter() - start

        all_same = all(r == "hello world test" for r in results)
        total_time_per_call = elapsed / N
        print(f"\n  Parallel transcription: {N} concurrent in {elapsed:.3f}s")
        print(f"  Avg per call (wall): {total_time_per_call * 1000:.1f}ms")
        print(f"  All results correct: {all_same}")

        # Если бы было последовательно: 10 × 50ms = 500ms
        # Параллельно должно быть ~50-100ms (один HTTP turnaround)
        print(
            f"  Sequential would be: {N * 0.05:.3f}s, actual parallel: {elapsed:.3f}s"
        )

        assert all_same
        assert elapsed < 1.0  # parallel should complete in < 1s

    @pytest.mark.asyncio
    async def test_parallel_with_budget_contention(self, service, test_audio):
        """50 параллельных get_transcription — проверка стабильности + budget."""
        N = 50
        mock_client_cls = self._mock_httpx(delay=0.02)

        with patch("bot.services.voice_service.httpx.AsyncClient", mock_client_cls):
            with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-xxx"}):
                start = time.perf_counter()
                tasks = [
                    service.get_transcription(test_audio, duration_seconds=5.0)
                    for _ in range(N)
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                elapsed = time.perf_counter() - start

        success = sum(1 for r in results if r == "hello world test")
        errors = [r for r in results if isinstance(r, Exception)]
        data = await _read_budget()
        expected_budget = N * 5.0

        print(f"\n  High load transcription: {N} concurrent in {elapsed:.3f}s")
        print(f"  Success: {success}/{N}, Errors: {len(errors)}")
        print(
            f"  Budget: {data['total_seconds']:.0f}s / {expected_budget:.0f}s expected"
        )
        if errors:
            for e in errors[:3]:
                print(f"    Error: {e}")

        assert success >= N * 0.9  # at least 90% success rate
        # С атомарным инкрементом budget должен сойтись
        budget_diff = abs(data["total_seconds"] - expected_budget)
        assert budget_diff < 1.0, (
            f"Budget mismatch: expected {expected_budget}, got {data['total_seconds']}"
        )

    @pytest.mark.asyncio
    async def test_long_duration_rejected(self, service, test_audio):
        """Длительное сообщение под нагрузкой — мгновенный reject без HTTP вызова."""
        N = 30
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-xxx"}):
            tasks = [
                service.get_transcription(test_audio, duration_seconds=999.0)
                for _ in range(N)
            ]
            start = time.perf_counter()
            results = await asyncio.gather(*tasks, return_exceptions=True)
            elapsed = time.perf_counter() - start

        valids = [r for r in results if isinstance(r, ValueError)]
        non_valids = [r for r in results if not isinstance(r, ValueError)]

        print(f"\n  Long voice rejection: {len(valids)}/{N} rejected as ValueError")
        print(f"  Time for {N} concurrent: {elapsed:.3f}s ({N / elapsed:.0f} reject/s)")
        print(f"  Non-ValueError: {len(non_valids)}")

        assert all("слишком длинное" in str(r) for r in valids)


# =============================================================================
# Тест 5: Полный цикл голосового сообщения (моки)
# =============================================================================


@pytest.mark.slow
class TestFullVoiceCycle:
    """Симуляция полного цикла: скачивание → транскрибация → ответ."""

    @pytest.mark.asyncio
    async def test_parallel_voice_cycles(self, tmp_path):
        """10 полных голосовых циклов параллельно."""
        N = 10

        async def full_cycle(user_id: int):
            """
            Симулирует:
            1. VoiceService() создаётся
            2. check_duration
            3. check_daily_budget
            4. get_transcription (мок)
            """
            voice_svc = VoiceService()

            # Мок duration
            duration = 30.0
            ok, msg = voice_svc.check_duration(duration)
            assert ok, f"Duration check failed: {msg}"

            ok, msg = await voice_svc.check_daily_budget(duration)
            assert ok, f"Budget check failed: {msg}"

            # Мок get_transcription
            async def mock_transcription(path, **kwargs):
                await asyncio.sleep(0.02)  # ~20ms network latency
                await voice_svc._update_budget(duration)
                return f"user {user_id} says hello"

            with patch.object(voice_svc, "get_transcription", mock_transcription):
                text = await voice_svc.get_transcription("/fake/path.ogg")
                assert "hello" in text

            # Мок AI tutor
            await asyncio.sleep(0.01)

            return f"user={user_id}, text={text}"

        start = time.perf_counter()
        results = await asyncio.gather(*[full_cycle(i) for i in range(N)])
        elapsed = time.perf_counter() - start

        print(f"\n  Full voice cycles: {N} parallel in {elapsed:.3f}s")
        print(f"  Throughput: {N / elapsed:.1f} cycles/s")
        print(f"  Results: {len(results)}")

        assert len(results) == N
        assert elapsed < 5.0


# =============================================================================
# Тест 6: Длительная стабильность (стресс)
# =============================================================================


@pytest.mark.stress
class TestStability:
    """Длительная нагрузка — 5 сек постоянных операций."""

    @pytest.mark.asyncio
    async def test_sustained_load(self, service):
        """Постоянная нагрузка на check_duration + check_daily_budget."""
        DURATION_SEC = 5

        async def hammer():
            count = 0
            end = time.perf_counter() + DURATION_SEC
            while time.perf_counter() < end:
                service.check_duration(30.0)
                service.check_duration(999.0)
                await service.check_daily_budget(30.0)
                await service.check_daily_budget(999.0)
                count += 1
            return count

        start = time.perf_counter()
        results = await asyncio.gather(*[hammer() for _ in range(10)])
        elapsed = time.perf_counter() - start

        total_calls = sum(results)
        ops_per_sec = total_calls / elapsed

        print(f"\n  Sustained load: {DURATION_SEC}s, 10 concurrent workers")
        print(f"  Total calls: {total_calls}")
        print(f"  Ops/sec: {ops_per_sec:.0f}")

        assert ops_per_sec > 100
