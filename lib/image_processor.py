"""
BUYMA向け商品画像処理モジュール。

処理パイプライン:
  1. 画像取得    : URLまたはローカルファイルから読み込み
  2. 背景除去    : AI（rembg / 外部APIプラグイン）で背景を除去
  3. 背景追加    : BUYMA映えするグラデーション or 白背景を合成
  4. リサイズ    : BUYMA推奨サイズ（最大辺1200px、最小辺300px）に調整
  5. 最適化      : JPEG圧縮・ファイルサイズを最大2MBに制限

外部AIの差し替え方法（Nano Banana 2等）:
  BackgroundProcessor を継承して remove_background() を実装するだけ:

    class NanoBanana2Processor(BackgroundProcessor):
        def remove_background(self, image: Image.Image) -> Image.Image:
            # Nano Banana 2 APIを呼び出す
            resp = requests.post(
                "https://api.nanobanana2.example.com/remove-bg",
                files={"image": image_to_bytes(image)},
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
            return Image.open(io.BytesIO(resp.content))

    processor = BUYMAImageProcessor(bg_processor=NanoBanana2Processor(api_key="..."))

環境変数:
  BG_REMOVAL_BACKEND: "rembg" (default) | "removebg" | "custom"
  REMOVE_BG_API_KEY  : remove.bg API キー（backend=removebg 時に必要）
  IMAGE_OUTPUT_DIR   : 加工済み画像の保存先ディレクトリ (default: ./processed_images)
"""

from __future__ import annotations

import io
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# BUYMA 画像仕様
_BUYMA_MAX_SIDE = 1200      # px（長辺上限）
_BUYMA_MIN_SIDE = 300       # px（長辺下限推奨）
_BUYMA_MAX_FILE_MB = 2.0    # MB
_BUYMA_ASPECT_RATIO = 1.0   # 正方形推奨（1:1）


# ============================================================================
# 背景除去の抽象基底クラス（差し替えインターフェース）
# ============================================================================

class BackgroundProcessor(ABC):
    """背景除去処理の抽象インターフェース。

    Nano Banana 2 や remove.bg など任意のサービスを差し込める。
    """

    @abstractmethod
    def remove_background(self, image: "Image.Image") -> "Image.Image":
        """背景を除去して RGBA 画像を返す。"""
        ...

    @property
    def name(self) -> str:
        return self.__class__.__name__


class RembgProcessor(BackgroundProcessor):
    """rembg（オープンソースAI）を使った背景除去。

    初回実行時にモデルを自動ダウンロード（約100MB）。
    ネット環境が必要。
    """

    def remove_background(self, image: "Image.Image") -> "Image.Image":
        try:
            from rembg import remove
        except ImportError:
            raise ImportError(
                "rembg が未インストールです。\n"
                "  pip install rembg[gpu]  # GPU環境\n"
                "  pip install rembg       # CPU環境"
            )

        from PIL import Image
        img_bytes = _image_to_png_bytes(image)
        result_bytes = remove(img_bytes)
        return Image.open(io.BytesIO(result_bytes)).convert("RGBA")


class RemoveBgAPIProcessor(BackgroundProcessor):
    """remove.bg の Web API を使った背景除去。

    精度が高いが有料（50枚/月 無料枠）。
    https://www.remove.bg/api
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def remove_background(self, image: "Image.Image") -> "Image.Image":
        from PIL import Image
        img_bytes = _image_to_png_bytes(image)
        resp = requests.post(
            "https://api.remove.bg/v1.0/removebg",
            files={"image_file": ("image.png", img_bytes, "image/png")},
            data={"size": "auto"},
            headers={"X-Api-Key": self._api_key},
            timeout=30,
        )
        resp.raise_for_status()
        return Image.open(io.BytesIO(resp.content)).convert("RGBA")


class NanoBanana2Processor(BackgroundProcessor):
    """Nano Banana 2 API を使った背景除去。

    NOTE: エンドポイントURLとリクエスト形式はサービス仕様に合わせて更新してください。

    環境変数:
      NANO_BANANA2_API_KEY    : API認証キー
      NANO_BANANA2_ENDPOINT   : APIエンドポイントURL
    """

    DEFAULT_ENDPOINT = os.getenv(
        "NANO_BANANA2_ENDPOINT",
        "https://api.nanobanana2.example.com/v1/remove-background",
    )

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.getenv("NANO_BANANA2_API_KEY", "")
        if not self._api_key:
            logger.warning("NANO_BANANA2_API_KEY が設定されていません。")

    def remove_background(self, image: "Image.Image") -> "Image.Image":
        from PIL import Image
        img_bytes = _image_to_png_bytes(image)
        resp = requests.post(
            self.DEFAULT_ENDPOINT,
            files={"image": ("image.png", img_bytes, "image/png")},
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=60,
        )
        resp.raise_for_status()
        return Image.open(io.BytesIO(resp.content)).convert("RGBA")


# ============================================================================
# 背景スタイル
# ============================================================================

@dataclass
class BackgroundStyle:
    """合成する背景の設定。"""

    mode: str = "white"          # "white" | "gradient" | "color"
    color: tuple = (255, 255, 255)       # mode="color" 時の単色
    gradient_top: tuple = (248, 248, 250)   # グラデーション上端
    gradient_bottom: tuple = (255, 255, 255)  # グラデーション下端
    add_shadow: bool = True      # 商品に影を追加するか
    shadow_opacity: int = 30     # 影の不透明度 (0-255)
    padding_ratio: float = 0.08  # 余白比率（画像辺に対する割合）


BUYMA_DEFAULT_BG = BackgroundStyle(
    mode="gradient",
    gradient_top=(250, 250, 252),
    gradient_bottom=(255, 255, 255),
    add_shadow=True,
    shadow_opacity=25,
    padding_ratio=0.08,
)

BUYMA_WHITE_BG = BackgroundStyle(
    mode="white",
    add_shadow=False,
    padding_ratio=0.05,
)


# ============================================================================
# 処理結果
# ============================================================================

@dataclass
class ProcessedImage:
    """画像処理の結果を保持するデータクラス。"""

    source_url: str
    output_path: str           # 保存先ファイルパス
    width: int
    height: int
    file_size_bytes: int
    format: str
    success: bool
    error: Optional[str] = None

    @property
    def file_size_mb(self) -> float:
        return self.file_size_bytes / (1024 * 1024)

    def __str__(self) -> str:
        if not self.success:
            return f"[FAILED] {self.source_url} — {self.error}"
        return (
            f"[OK] {Path(self.output_path).name}"
            f" ({self.width}×{self.height}, {self.file_size_mb:.1f}MB)"
        )


# ============================================================================
# メイン画像処理クラス
# ============================================================================

class BUYMAImageProcessor:
    """仕入れ元画像をBUYMA最適化済み画像に変換するクラス。

    Args:
        bg_processor: 背景除去に使用する BackgroundProcessor の実装。
                      None の場合は環境変数 BG_REMOVAL_BACKEND に基づき自動選択。
        bg_style: 合成する背景のスタイル設定。
        output_dir: 処理済み画像の保存先。
        output_size: 最終的な正方形サイズ (px)。0 で自動（最大辺1200px）。
        jpeg_quality: JPEG圧縮品質 (1-95)。
    """

    def __init__(
        self,
        bg_processor: Optional[BackgroundProcessor] = None,
        bg_style: BackgroundStyle = BUYMA_DEFAULT_BG,
        output_dir: str = "",
        output_size: int = 0,
        jpeg_quality: int = 90,
    ) -> None:
        self._bg_processor = bg_processor or _auto_select_processor()
        self._bg_style = bg_style
        self._output_dir = Path(output_dir or os.getenv("IMAGE_OUTPUT_DIR", "processed_images"))
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._output_size = output_size
        self._jpeg_quality = jpeg_quality

        logger.info(
            "BUYMAImageProcessor initialized: backend=%s, output_dir=%s",
            self._bg_processor.name, self._output_dir,
        )

    def process_url(self, url: str, filename: str = "") -> ProcessedImage:
        """URLから画像を取得し、BUYMA最適化を適用して保存する。"""
        try:
            from PIL import Image
            raw_bytes = _download_image(url)
            img = Image.open(io.BytesIO(raw_bytes)).convert("RGBA")
            return self._process(img, url, filename)
        except Exception as e:
            logger.error("画像処理失敗 [%s]: %s", url, e, exc_info=True)
            return ProcessedImage(
                source_url=url, output_path="", width=0, height=0,
                file_size_bytes=0, format="", success=False, error=str(e),
            )

    def process_file(self, path: str) -> ProcessedImage:
        """ローカルファイルをBUYMA最適化する。"""
        try:
            from PIL import Image
            img = Image.open(path).convert("RGBA")
            return self._process(img, f"file://{path}", Path(path).stem)
        except Exception as e:
            return ProcessedImage(
                source_url=path, output_path="", width=0, height=0,
                file_size_bytes=0, format="", success=False, error=str(e),
            )

    def process_batch(self, urls: list[tuple[str, str]]) -> list[ProcessedImage]:
        """複数URLをバッチ処理する。

        Args:
            urls: (url, filename) のリスト。
        """
        results = []
        for url, filename in urls:
            result = self.process_url(url, filename)
            results.append(result)
            logger.info("  %s", result)
        return results

    # ------------------------------------------------------------------
    # 内部処理
    # ------------------------------------------------------------------

    def _process(
        self, img: "Image.Image", source_url: str, filename: str
    ) -> ProcessedImage:
        from PIL import Image

        logger.debug("背景除去開始: %s (バックエンド: %s)", source_url, self._bg_processor.name)
        fg = self._bg_processor.remove_background(img)

        logger.debug("背景合成中...")
        output_img = self._compose_background(fg)

        logger.debug("リサイズ中...")
        output_img = self._resize_for_buyma(output_img)

        output_path = self._save(output_img, filename or _url_to_filename(source_url))
        stat = output_path.stat()

        return ProcessedImage(
            source_url=source_url,
            output_path=str(output_path),
            width=output_img.width,
            height=output_img.height,
            file_size_bytes=stat.st_size,
            format="JPEG",
            success=True,
        )

    def _compose_background(self, fg_rgba: "Image.Image") -> "Image.Image":
        """前景（透過PNG）に背景を合成する。"""
        from PIL import Image, ImageDraw, ImageFilter

        style = self._bg_style
        w, h = fg_rgba.size

        # 背景レイヤー
        bg = Image.new("RGBA", (w, h), (255, 255, 255, 255))

        if style.mode == "gradient":
            bg = _create_gradient(w, h, style.gradient_top, style.gradient_bottom)
        elif style.mode == "color":
            bg = Image.new("RGBA", (w, h), (*style.color, 255))

        # 影レイヤー
        if style.add_shadow and fg_rgba.mode == "RGBA":
            shadow = _create_shadow(fg_rgba, style.shadow_opacity)
            bg = Image.alpha_composite(bg, shadow)

        # 前景を合成
        bg = Image.alpha_composite(bg, fg_rgba)
        return bg.convert("RGB")

    def _resize_for_buyma(self, img: "Image.Image") -> "Image.Image":
        """BUYMAの仕様に合わせてリサイズする。"""
        from PIL import Image

        target = self._output_size if self._output_size > 0 else _BUYMA_MAX_SIDE

        # 正方形にクロップ（アスペクト比1:1）
        w, h = img.size
        size = min(w, h)
        left = (w - size) // 2
        top = (h - size) // 2
        img = img.crop((left, top, left + size, top + size))

        # パディングを加えたキャンバスに配置
        pad = int(size * self._bg_style.padding_ratio)
        content_size = size - pad * 2
        content_size = max(content_size, _BUYMA_MIN_SIDE)

        resized_content = img.resize(
            (content_size, content_size), Image.LANCZOS
        )
        canvas_size = content_size + pad * 2

        if self._bg_style.mode == "gradient":
            canvas = _create_gradient(
                canvas_size, canvas_size,
                self._bg_style.gradient_top,
                self._bg_style.gradient_bottom,
            ).convert("RGB")
        else:
            canvas = Image.new("RGB", (canvas_size, canvas_size), (255, 255, 255))

        canvas.paste(resized_content, (pad, pad))

        # 最終サイズに統一
        final_size = min(target, canvas_size)
        return canvas.resize((final_size, final_size), Image.LANCZOS)

    def _save(self, img: "Image.Image", filename: str) -> Path:
        """画像を保存し、ファイルサイズが上限内に収まるよう品質を調整する。"""
        output_path = self._output_dir / f"{filename}.jpg"
        quality = self._jpeg_quality
        while quality >= 60:
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality, optimize=True)
            size_mb = len(buf.getvalue()) / (1024 * 1024)
            if size_mb <= _BUYMA_MAX_FILE_MB:
                break
            quality -= 5

        with open(output_path, "wb") as f:
            f.write(buf.getvalue())

        logger.debug(
            "保存完了: %s (%.1fMB, quality=%d)",
            output_path, size_mb, quality,
        )
        return output_path


# ============================================================================
# ユーティリティ
# ============================================================================

def _auto_select_processor() -> BackgroundProcessor:
    """環境変数 BG_REMOVAL_BACKEND に基づいてプロセッサーを選択する。"""
    backend = os.getenv("BG_REMOVAL_BACKEND", "rembg").lower()
    if backend == "removebg":
        api_key = os.getenv("REMOVE_BG_API_KEY", "")
        if not api_key:
            logger.warning("REMOVE_BG_API_KEY 未設定。rembg にフォールバックします。")
            return RembgProcessor()
        return RemoveBgAPIProcessor(api_key)
    if backend == "nanobanana2":
        return NanoBanana2Processor()
    return RembgProcessor()


def _download_image(url: str, timeout: int = 30) -> bytes:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.content


def _image_to_png_bytes(img: "Image.Image") -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _create_gradient(
    w: int, h: int,
    top_color: tuple, bottom_color: tuple
) -> "Image.Image":
    from PIL import Image
    base = Image.new("RGBA", (w, h))
    for y in range(h):
        t = y / max(h - 1, 1)
        r = int(top_color[0] + (bottom_color[0] - top_color[0]) * t)
        g = int(top_color[1] + (bottom_color[1] - top_color[1]) * t)
        b = int(top_color[2] + (bottom_color[2] - top_color[2]) * t)
        from PIL import ImageDraw
        draw = ImageDraw.Draw(base)
        draw.line([(0, y), (w, y)], fill=(r, g, b, 255))
    return base


def _create_shadow(fg: "Image.Image", opacity: int) -> "Image.Image":
    from PIL import Image, ImageFilter
    shadow_layer = Image.new("RGBA", fg.size, (0, 0, 0, 0))
    if fg.mode != "RGBA":
        return shadow_layer
    alpha = fg.split()[3]
    shadow = Image.new("RGBA", fg.size, (0, 0, 0, 0))
    shadow.putalpha(alpha)
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=8))
    # 影を少し下にオフセット
    offset_shadow = Image.new("RGBA", fg.size, (0, 0, 0, 0))
    offset = int(fg.height * 0.02)
    offset_shadow.paste(shadow, (offset, offset))
    # 不透明度を調整
    r, g, b, a = offset_shadow.split()
    a = a.point(lambda x: int(x * opacity / 255))
    shadow_dark = Image.new("RGBA", fg.size, (20, 20, 20, 0))
    shadow_dark.putalpha(a)
    return shadow_dark


def _url_to_filename(url: str) -> str:
    import re
    from urllib.parse import urlparse
    path = urlparse(url).path
    name = Path(path).stem or "product"
    return re.sub(r"[^\w\-]", "_", name)[:50]
