"""asyncio.run() 互換ラッパー。

既存イベントループが動作中の場合（Jupyter / 入れ子呼出し等）でも
安全にコルーチンを実行できるようにする。
"""

from __future__ import annotations

import asyncio
from typing import TypeVar

T = TypeVar("T")


def run_sync(coro: asyncio.coroutines, *_: object) -> T:  # type: ignore[type-arg]
    """同期コンテキストからコルーチンを実行する。

    * イベントループが存在しない → ``asyncio.run()`` で実行
    * イベントループが存在 & 実行中 → 新スレッドで ``asyncio.run()`` を起動
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is None:
        return asyncio.run(coro)

    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, coro)
        return future.result()
