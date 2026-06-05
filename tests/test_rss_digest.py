import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.ai.rss_fetcher import RssFetchResult
from app.executors.rss_digest import _select_source_diverse_items, run


class RssDigestTest(unittest.TestCase):
    def test_selects_distinct_sources_before_duplicate_publishers(self):
        items = [
            {"title": "BBC newest", "source": "BBC", "timestamp": 30},
            {"title": "BBC older", "source": "BBC", "timestamp": 20},
            {"title": "Reuters", "source": "Reuters", "timestamp": 10},
        ]

        selected = _select_source_diverse_items(items, 2)

        self.assertEqual([item["source"] for item in selected], ["BBC", "Reuters"])

    @patch("app.executors.rss_digest.fetch_rss_items")
    def test_fails_transparently_when_ten_sources_are_not_available(self, fetch_mock):
        fetch_mock.return_value = RssFetchResult(
            feed_title="Global feed",
            items=[
                {
                    "title": f"Headline {index}",
                    "source": f"Publisher {index}",
                    "timestamp": index,
                }
                for index in range(1, 10)
            ],
        )
        task = SimpleNamespace(name="Global News", timezone="Asia/Shanghai")

        status, output, error = run(
            task,
            {
                "feed_url": "https://example.com/world.xml",
                "limit": 10,
                "min_sources": 10,
                "summary_mode": "rules",
                "notify": False,
            },
        )

        self.assertEqual(status, "failed")
        self.assertEqual(output, "")
        self.assertIn("Only 9 distinct news sources", error)


if __name__ == "__main__":
    unittest.main()
