"""async_compat モジュールのテスト。"""

from __future__ import annotations

import asyncio

from lib.async_compat import run_sync


async def _add(a: int, b: int) -> int:
    await asyncio.sleep(0)
    return a + b


class TestRunSync:
    def test_basic(self):
        assert run_sync(_add(2, 3)) == 5

    def test_returns_value(self):
        result = run_sync(_add(10, 20))
        assert result == 30

    def test_exception_propagates(self):
        async def _raise() -> None:
            raise ValueError("boom")

        import pytest
        with pytest.raises(ValueError, match="boom"):
            run_sync(_raise())
