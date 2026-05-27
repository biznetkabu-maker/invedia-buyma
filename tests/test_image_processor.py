"""image_processor モジュールのユニットテスト。"""

import unittest

from lib.image_processor import (
    BUYMA_DEFAULT_BG,
    BUYMA_WHITE_BG,
    BackgroundStyle,
    ProcessedImage,
    _BUYMA_MAX_SIDE,
)


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


if __name__ == "__main__":
    unittest.main()
