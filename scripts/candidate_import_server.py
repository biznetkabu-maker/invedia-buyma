#!/usr/bin/env python3
"""
白パネル（ブックマークレット）から TSV を POST してシートに追記するローカルサーバー。

起動: py scripts/candidate_import_server.py
      または 2_候補_取込_サーバー起動.bat

BUYMA ページの fetch は http://127.0.0.1 のみ（credentials.json は PC 上のまま）。
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _load_import_tsv():
    import importlib.util

    path = Path(__file__).resolve().parent / "candidate_import.py"
    spec = importlib.util.spec_from_file_location("candidate_import", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod.import_tsv_text


import_tsv_text = _load_import_tsv()

DEFAULT_PORT = 18765
HOST = "127.0.0.1"


class ImportHandler(BaseHTTPRequestHandler):
    server_version = "candidate-import/1"

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, code: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] in ("/", "/health"):
            self._json(
                200,
                {
                    "ok": True,
                    "service": "candidate-import",
                    "hint": "POST /import with text/plain TSV body",
                },
            )
            return
        self._json(404, {"ok": False, "message": "not found"})

    def do_POST(self) -> None:
        if self.path.split("?", 1)[0] != "/import":
            self._json(404, {"ok": False, "message": "not found"})
            return
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            self._json(400, {"ok": False, "message": "empty body"})
            return
        if length > 5_000_000:
            self._json(413, {"ok": False, "message": "body too large"})
            return
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        print(f"取込リクエスト受信 ({len(raw)} 文字)")
        result = import_tsv_text(raw, verbose=True)
        code = 200 if result.ok else 400
        self._json(code, result.to_json_dict())


def main() -> int:
    port = int(os.environ.get("CANDIDATE_IMPORT_PORT", DEFAULT_PORT))
    httpd = ThreadingHTTPServer((HOST, port), ImportHandler)
    print()
    print(f"  候補取込サーバー起動: http://{HOST}:{port}")
    print("  白パネルの「シートに取込」が使えます。この窓は閉じないでください。")
    print("  終了: Ctrl+C")
    print()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  停止しました。")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
