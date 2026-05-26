"""scripts/setup_simple.py のユニットテスト。"""

from __future__ import annotations

import importlib.util
import pathlib


def _load():
    path = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "setup_simple.py"
    spec = importlib.util.spec_from_file_location("setup_simple", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_extract_spreadsheet_id_from_url():
    mod = _load()
    url = "https://docs.google.com/spreadsheets/d/abc123XYZ/edit#gid=0"
    assert mod.extract_spreadsheet_id(url) == "abc123XYZ"


def test_extract_spreadsheet_id_raw():
    mod = _load()
    assert mod.extract_spreadsheet_id("  raw-id-99  ") == "raw-id-99"
