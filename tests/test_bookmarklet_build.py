"""scripts/build_buyma_bookmarklet.py のユーティリティ検証。"""

from __future__ import annotations

import importlib.util
import pathlib


def _load_build_module():
    root = pathlib.Path(__file__).resolve().parents[1]
    path = root / "scripts" / "build_buyma_bookmarklet.py"
    spec = importlib.util.spec_from_file_location("build_buyma_bookmarklet", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_minify_js_strips_block_comment_only():
    mod = _load_build_module()
    out = mod.minify_js("/* BLOCK */ x = 1;\n// line comment kept\n y = 2")
    assert "BLOCK" not in out
    assert "/*" not in out
    assert "line comment kept" in out  # URL と誤認しないため // 行コメントは削除しない
    assert "x = 1" in out
    assert "y = 2" in out
