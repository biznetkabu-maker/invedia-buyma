#!/usr/bin/env python3
"""buyma_candidates.source.js をビルドして bookmarklets/ に書き出す。"""

from __future__ import annotations

import base64
import gzip
import pathlib
import re

# 外部 script 読込は BUYMA / Chrome 設定で失敗しやすい → gzip インラインを既定にする
_LOADER_SRC = (
    "javascript:(function(){"
    'if(!/(^|\\.)buyma\\.com$/i.test(location.hostname)){'
    'alert("BUYMA（buyma.com）のページで実行してください");return;}'
    'var done=false;'
    "function go(u,next){"
    'if(done)return;var s=document.createElement("script");'
    's.src=u;s.onload=function(){done=true;};'
    's.onerror=function(){if(next)next();else alert("読み込み失敗。下の gzip 版ブックマークを試してください。");};'
    "(document.body||document.documentElement).appendChild(s);}"
    'go("https://raw.githubusercontent.com/biznetkabu-maker/invedia-automation/main/bookmarklets/buyma_candidates.run.js?t="+Date.now(),'
    'function(){go("https://cdn.jsdelivr.net/gh/biznetkabu-maker/invedia-automation@main/bookmarklets/buyma_candidates.run.js?t="+Date.now());});'
    "})();"
)

_TEST_SRC = "javascript:alert('BUYMAブックマーク OK\\n次に本番URLを登録してください');"


def minify_js(src: str) -> str:
    s = re.sub(r"/\*[\s\S]*?\*/", "", src)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def build_gzip_bookmarklet(body: str) -> str:
    """DecompressionStream + eval（Chrome 80+）。CSP に強いインライン実行。"""
    raw = gzip.compress(body.encode("utf-8"), compresslevel=9)
    b64 = base64.b64encode(raw).decode()
    b64_esc = b64.replace("\\", "\\\\").replace("'", "\\'")
    return (
        "javascript:(async function(){try{"
        'if(!/(^|\\.)buyma\\.com$/i.test(location.hostname)){'
        'alert("BUYMA（buyma.com）のページで実行してください");return;}'
        f"var b64='{b64_esc}';"
        "if(typeof DecompressionStream==='undefined'){"
        'alert("Chrome を最新にするか、BUYMA候補_F12実行.bat を使ってください");return;}'
        "var raw=Uint8Array.from(atob(b64),function(c){return c.charCodeAt(0)});"
        "var js=await new Response(new Blob([raw]).stream().pipeThrough("
        "new DecompressionStream('gzip'))).text();"
        "eval(js);"
        "}catch(e){alert('BUYMA候補エラー:\\n'+(e&&e.message?e.message:e));}"
        "})();"
    )


def _write_buyma_start_html(root: pathlib.Path, body: str, gzip_bm: str) -> None:
    """1ページで候補抽出（自動コピー + 任意でブックマーク）。"""
    template = root / "bookmarklets" / "buyma_start.template.html"
    out = root / "bookmarklets" / "buyma_start.html"
    html = template.read_text(encoding="utf-8")
    safe_body = body.replace("</", "<\\/")
    safe_gzip = gzip_bm.replace("</", "<\\/")
    html = html.replace("%%SCRIPT_BODY%%", safe_body)
    html = html.replace("%%GZIP_BOOKMARKLET%%", safe_gzip)
    out.write_text(html, encoding="utf-8")
    print(f"Wrote {out}")


def _write_install_html(root: pathlib.Path, bookmark: str, loader: str, gzip_bm: str) -> None:
    template_path = root / "bookmarklets" / "install_bookmarklet.template.html"
    out_path = root / "bookmarklets" / "install_bookmarklet.html"
    html = template_path.read_text(encoding="utf-8")
    html = html.replace("%%BOOKMARKLET_GZIP%%", gzip_bm.replace("</", "<\\/"))
    html = html.replace("%%BOOKMARKLET_LOADER%%", loader.replace("</", "<\\/"))
    html = html.replace("%%BOOKMARKLET_FULL%%", bookmark.replace("</", "<\\/"))
    out_path.write_text(html, encoding="utf-8")
    print(f"Wrote {out_path}")


def main() -> None:
    import subprocess

    root = pathlib.Path(__file__).resolve().parents[1]
    bl = root / "bookmarklets"
    src = bl / "buyma_candidates.source.js"
    subprocess.run(["node", "--check", str(src)], check=True)
    body = minify_js(src.read_text(encoding="utf-8"))
    if not body.endswith(";"):
        body += ";"

    bookmark = "javascript:" + body
    loader = _LOADER_SRC
    gzip_bm = build_gzip_bookmarklet(body)

    (bl / "buyma_candidates.run.js").write_text(body + "\n", encoding="utf-8")
    (bl / "buyma_bookmarklet.txt").write_text(bookmark + "\n", encoding="utf-8")
    (bl / "buyma_bookmarklet_loader.txt").write_text(loader + "\n", encoding="utf-8")
    (bl / "buyma_bookmarklet_gzip.txt").write_text(gzip_bm + "\n", encoding="utf-8")
    (bl / "buyma_bookmarklet_test.txt").write_text(_TEST_SRC + "\n", encoding="utf-8")

    print(f"Wrote buyma_candidates.run.js ({len(body)} chars)")
    print(f"Wrote buyma_bookmarklet.txt ({len(bookmark)} chars)")
    print(f"Wrote buyma_bookmarklet_loader.txt ({len(loader)} chars)")
    print(f"Wrote buyma_bookmarklet_gzip.txt ({len(gzip_bm)} chars)  <-- default install")
    _write_install_html(root, bookmark, loader, gzip_bm)
    _write_buyma_start_html(root, body, gzip_bm)


if __name__ == "__main__":
    main()
