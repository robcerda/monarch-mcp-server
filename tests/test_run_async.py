"""Tests for run_async function."""

import asyncio
from concurrent.futures import TimeoutError as FuturesTimeoutError

import pytest

from monarch_mcp_server.server import API_TIMEOUT_SECONDS, run_async


class TestRunAsync:
    """Tests for run_async function."""

    def test_run_async_returns_result(self) -> None:
        """Test that run_async correctly returns coroutine result."""

        async def simple_coro() -> str:
            return "success"

        result = run_async(simple_coro())
        assert result == "success"

    def test_run_async_with_dict_result(self) -> None:
        """Test that run_async handles dict results."""

        async def dict_coro() -> dict:
            return {"key": "value", "count": 42}

        result = run_async(dict_coro())
        assert result == {"key": "value", "count": 42}

    def test_run_async_preserves_exception(self) -> None:
        """Test that run_async propagates exceptions from coroutine."""

        async def failing_coro() -> None:
            raise ValueError("Test error")

        with pytest.raises(ValueError, match="Test error"):
            run_async(failing_coro())

    def test_run_async_with_short_timeout(self) -> None:
        """Test that run_async respects custom timeout."""

        async def slow_coro() -> str:
            await asyncio.sleep(5)
            return "done"

        with pytest.raises(FuturesTimeoutError):
            run_async(slow_coro(), timeout=1)

    def test_run_async_default_timeout_is_set(self) -> None:
        """Test that default timeout constant is reasonable."""
        assert API_TIMEOUT_SECONDS == 30

    def test_run_async_with_async_operations(self) -> None:
        """Test that run_async handles multiple awaits."""

        async def multi_await_coro() -> int:
            await asyncio.sleep(0.01)
            x = 1
            await asyncio.sleep(0.01)
            x += 1
            return x

        result = run_async(multi_await_coro())
        assert result == 2
