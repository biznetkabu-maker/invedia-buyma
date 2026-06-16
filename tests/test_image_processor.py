"""image_processor モジュールのユニットテスト。"""

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from lib.image_processor import (
    _BUYMA_MAX_SIDE,
    BUYMA_DEFAULT_BG,
    BUYMA_WHITE_BG,
    BackgroundProcessor,
    BackgroundStyle,
    BUYMAImageProcessor,
    ProcessedImage,
    RembgProcessor,
    _auto_select_processor,
    _create_gradient,
    _create_shadow,
    _image_to_png_bytes,
    _url_to_filename,
)


class _FakeProcessor(BackgroundProcessor):
    """背景除去をスキップして入力画像をそのまま返す。"""

    def remove_background(self, image):
        return image

    @property
    def name(self):
        return "fake"


def _make_rgba(w=300, h=400):
    return Image.new("RGBA", (w, h), (120, 130, 140, 255))


class TestProcessedImage(unittest.TestCase):
    def test_file_size_mb(self):
        pi = ProcessedImage(
            source_url="https://example.com/img.jpg",
            output_path="/tmp/out.jpg",
            width=800,
            height=800,
            file_size_bytes=1_048_576,
            format="JPEG",
            success=True,
        )
        self.assertAlmostEqual(pi.file_size_mb, 1.0)

    def test_str_success(self):
        pi = ProcessedImage(
            source_url="https://example.com/img.jpg",
            output_path="/tmp/product.jpg",
            width=1200,
            height=1200,
            file_size_bytes=500_000,
            format="JPEG",
            success=True,
        )
        text = str(pi)
        self.assertIn("OK", text)
        self.assertIn("product.jpg", text)

    def test_str_failure(self):
        pi = ProcessedImage(
            source_url="https://example.com/img.jpg",
            output_path="",
            width=0,
            height=0,
            file_size_bytes=0,
            format="",
            success=False,
            error="Download failed",
        )
        text = str(pi)
        self.assertIn("FAILED", text)
        self.assertIn("Download failed", text)


class TestBackgroundStyle(unittest.TestCase):
    def test_default_mode_is_gradient(self):
        self.assertEqual(BUYMA_DEFAULT_BG.mode, "gradient")

    def test_white_bg_no_shadow(self):
        self.assertFalse(BUYMA_WHITE_BG.add_shadow)
        self.assertEqual(BUYMA_WHITE_BG.mode, "white")

    def test_custom_style(self):
        style = BackgroundStyle(mode="color", color=(200, 200, 200))
        self.assertEqual(style.color, (200, 200, 200))


class TestConstants(unittest.TestCase):
    def test_max_side(self):
        self.assertEqual(_BUYMA_MAX_SIDE, 1200)


class TestHelpers(unittest.TestCase):
    def test_create_gradient_dimensions(self):
        img = _create_gradient(20, 30, (0, 0, 0), (255, 255, 255))
        self.assertEqual(img.size, (20, 30))
        self.assertEqual(img.mode, "RGBA")

    def test_create_shadow_rgba(self):
        fg = _make_rgba(50, 60)
        shadow = _create_shadow(fg, 30)
        self.assertEqual(shadow.size, (50, 60))

    def test_create_shadow_non_rgba_returns_blank(self):
        fg = Image.new("RGB", (40, 40), (10, 10, 10))
        shadow = _create_shadow(fg, 30)
        self.assertEqual(shadow.size, (40, 40))

    def test_image_to_png_bytes(self):
        data = _image_to_png_bytes(_make_rgba(10, 10))
        self.assertTrue(data.startswith(b"\x89PNG"))

    def test_url_to_filename_sanitizes(self):
        self.assertEqual(_url_to_filename("https://x.com/path/My Bag!.jpg"), "My_Bag_")

    def test_url_to_filename_default(self):
        self.assertEqual(_url_to_filename("https://x.com/"), "product")


class TestAutoSelectProcessor(unittest.TestCase):
    def test_default_rembg(self):
        with patch.dict("os.environ", {"BG_REMOVAL_BACKEND": "rembg"}):
            self.assertIsInstance(_auto_select_processor(), RembgProcessor)

    def test_removebg_without_key_falls_back(self):
        with patch.dict(
            "os.environ", {"BG_REMOVAL_BACKEND": "removebg", "REMOVE_BG_API_KEY": ""}
        ):
            self.assertIsInstance(_auto_select_processor(), RembgProcessor)


class TestBUYMAImageProcessor(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proc = BUYMAImageProcessor(
            bg_processor=_FakeProcessor(),
            output_dir=self.tmp.name,
            output_size=400,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_process_file_success(self):
        src = Path(self.tmp.name) / "in.png"
        _make_rgba().save(src)
        result = self.proc.process_file(str(src))
        self.assertTrue(result.success)
        self.assertTrue(Path(result.output_path).exists())
        self.assertEqual(result.format, "JPEG")
        self.assertEqual(result.width, result.height)

    def test_process_file_invalid_path(self):
        result = self.proc.process_file("/nonexistent/x.png")
        self.assertFalse(result.success)
        self.assertTrue(result.error)

    def test_process_url_success(self):
        buf = io.BytesIO()
        _make_rgba().save(buf, format="PNG")
        with patch(
            "lib.image_processor._download_image", return_value=buf.getvalue()
        ):
            result = self.proc.process_url("https://x.com/a.png", "myfile")
        self.assertTrue(result.success)
        self.assertIn("myfile", result.output_path)

    def test_process_url_download_error(self):
        with patch(
            "lib.image_processor._download_image", side_effect=OSError("boom")
        ):
            result = self.proc.process_url("https://x.com/a.png")
        self.assertFalse(result.success)

    def test_process_batch(self):
        buf = io.BytesIO()
        _make_rgba().save(buf, format="PNG")
        with patch(
            "lib.image_processor._download_image", return_value=buf.getvalue()
        ):
            results = self.proc.process_batch(
                [("https://x.com/1.png", "one"), ("https://x.com/2.png", "two")]
            )
        self.assertEqual(len(results), 2)
        self.assertTrue(all(r.success for r in results))

    def test_white_bg_style_no_shadow(self):
        proc = BUYMAImageProcessor(
            bg_processor=_FakeProcessor(),
            bg_style=BUYMA_WHITE_BG,
            output_dir=self.tmp.name,
            output_size=300,
        )
        src = Path(self.tmp.name) / "w.png"
        _make_rgba().save(src)
        result = proc.process_file(str(src))
        self.assertTrue(result.success)


if __name__ == "__main__":
    unittest.main()
