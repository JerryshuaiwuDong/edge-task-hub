import unittest
from types import SimpleNamespace
from unittest.mock import patch

import requests

from app.ai.rss_fetcher import RssFetchError, _entry_to_item, fetch_rss_items


class RssFetcherTest(unittest.TestCase):
    def test_uses_entry_publisher_instead_of_aggregator_name(self):
        entry = SimpleNamespace(
            title="Global headline",
            link="https://example.com/story",
            source={"title": "Reuters"},
            published_parsed=None,
            updated_parsed=None,
            published="",
            updated="",
            pubDate="",
            isoDate="",
        )

        item = _entry_to_item(entry, "Google News")

        self.assertEqual(item["source"], "Reuters")

    @patch("app.ai.rss_fetcher.requests.get")
    def test_ssl_failure_is_not_retried_without_verification(self, get_mock):
        get_mock.side_effect = requests.exceptions.SSLError("certificate verify failed")

        with self.assertRaises(RssFetchError):
            fetch_rss_items("https://example.com/feed.xml")

        get_mock.assert_called_once()
        self.assertNotIn("verify", get_mock.call_args.kwargs)

    @patch("app.ai.rss_fetcher.requests.get")
    def test_ssl_failure_remains_visible_when_explicit_fallback_is_used(self, get_mock):
        get_mock.side_effect = requests.exceptions.SSLError("certificate verify failed")
        fallback = [
            {
                "title": "Local fallback item",
                "link": "local://fallback",
                "source": "test",
                "timestamp": 1,
            }
        ]

        result = fetch_rss_items(
            "https://example.com/feed.xml",
            fallback_items=fallback,
        )

        self.assertTrue(result.feed_fallback)
        self.assertIn("certificate verify failed", result.feed_error)
        get_mock.assert_called_once()
        self.assertNotIn("verify", get_mock.call_args.kwargs)


if __name__ == "__main__":
    unittest.main()
