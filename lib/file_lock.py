"""ファイルロックユーティリティ。

JSON キャッシュファイルの読み書き時に flock を使った排他制御を提供する。
GitHub Actions の並列ジョブや複数プロセスからの同時書き込みによるデータ破損を防ぐ。

使い方:
    from lib.file_lock import atomic_json_read, atomic_json_write

    data = atomic_json_read(Path(".cache.json"))
    data["key"] = "value"
    atomic_json_write(Path(".cache.json"), data)
"""

from __future__ import annotations

import fcntl
import json
import logging
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def atomic_json_read(path: Path, default: Any = None) -> Any:
    """ファイルロック付きで JSON ファイルを読み込む。

    ファイルが存在しないかパース失敗の場合は default を返す。
    """
    if default is None:
        default = {}
    try:
        with open(path, encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            try:
                return json.load(f)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except FileNotFoundError:
        return default
    except (json.JSONDecodeError, OSError) as exc:
        logger.debug("JSON読み込み失敗 %s: %s", path, exc)
        return default


def atomic_json_write(path: Path, data: Any) -> bool:
    """ファイルロック付きで JSON ファイルを書き込む。

    一時ファイルに書き込んでから rename することで、
    書き込み中のクラッシュでもファイルが破損しない。
    """
    try:
        parent = path.parent
        parent.mkdir(parents=True, exist_ok=True)

        fd, tmp_path = tempfile.mkstemp(dir=str(parent), suffix=".tmp")
        try:
            with open(fd, "w", encoding="utf-8") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                try:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)
            Path(tmp_path).replace(path)
            return True
        except Exception:
            Path(tmp_path).unlink(missing_ok=True)
            raise
    except Exception as exc:
        logger.debug("JSON書き込み失敗 %s: %s", path, exc)
        return False
