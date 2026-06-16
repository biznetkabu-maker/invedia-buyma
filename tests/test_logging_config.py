"""logging_config.py のユニットテスト。"""

import json
import logging
import unittest

from lib.logging_config import (
    JSONFormatter,
    ScrapeMetrics,
    SiteMetrics,
    get_metrics,
    record_scrape,
    reset_metrics,
    setup_logging,
)


class TestJSONFormatter(unittest.TestCase):
    def test_format_basic(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="",
            lineno=0, msg="hello", args=(), exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)
        self.assertEqual(data["level"], "INFO")
        self.assertEqual(data["message"], "hello")
        self.assertIn("timestamp", data)

    def test_format_with_exception(self):
        formatter = JSONFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            import sys
            record = logging.LogRecord(
                name="test", level=logging.ERROR, pathname="",
                lineno=0, msg="error", args=(), exc_info=sys.exc_info(),
            )
        output = formatter.format(record)
        data = json.loads(output)
        self.assertIn("exception", data)
        self.assertIn("ValueError", data["exception"])


class TestSetupLogging(unittest.TestCase):
    def test_text_format(self):
        setup_logging(json_format=False)
        root = logging.getLogger()
        self.assertTrue(len(root.handlers) > 0)

    def test_json_format(self):
        setup_logging(json_format=True)
        root = logging.getLogger()
        self.assertIsInstance(root.handlers[0].formatter, JSONFormatter)

    def tearDown(self):
        setup_logging(json_format=False, level=logging.WARNING)


class TestSiteMetrics(unittest.TestCase):
    def test_initial_state(self):
        m = SiteMetrics(site="example.com")
        self.assertEqual(m.total, 0)
        self.assertEqual(m.success_rate, 0.0)
        self.assertEqual(m.avg_response_time, 0.0)

    def test_to_dict(self):
        m = SiteMetrics(site="example.com", total=10, success=8,
                        failure=2, total_response_time=5.0)
        d = m.to_dict()
        self.assertEqual(d["site"], "example.com")
        self.assertEqual(d["success_rate"], 0.8)
        self.assertEqual(d["avg_response_time"], 0.5)


class TestScrapeMetrics(unittest.TestCase):
    def test_record_and_summary(self):
        metrics = ScrapeMetrics()
        metrics.record("a.com", success=True, response_time=1.0)
        metrics.record("a.com", success=True, response_time=2.0)
        metrics.record("a.com", success=False, response_time=3.0)
        metrics.record("b.com", success=True, response_time=0.5)

        s = metrics.summary()
        self.assertEqual(s["total_scrapes"], 4)
        self.assertEqual(s["total_success"], 3)
        self.assertEqual(s["total_failure"], 1)
        self.assertEqual(len(s["sites"]), 2)

    def test_empty_summary(self):
        metrics = ScrapeMetrics()
        s = metrics.summary()
        self.assertEqual(s["total_scrapes"], 0)
        self.assertEqual(s["overall_success_rate"], 0.0)


class TestGlobalMetrics(unittest.TestCase):
    def setUp(self):
        reset_metrics()

    def test_record_and_get(self):
        record_scrape("test.com", success=True, response_time=1.0)
        m = get_metrics()
        self.assertIn("test.com", m.sites)
        self.assertEqual(m.sites["test.com"].total, 1)

    def test_reset(self):
        record_scrape("test.com", success=True)
        reset_metrics()
        m = get_metrics()
        self.assertEqual(len(m.sites), 0)


if __name__ == "__main__":
    unittest.main()
