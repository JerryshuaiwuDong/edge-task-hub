import unittest
from unittest.mock import patch

try:
    import pydantic_settings  # noqa: F401
except ModuleNotFoundError:
    pydantic_settings = None


@unittest.skipUnless(pydantic_settings, "Project settings dependency is not installed")
class NewsSummaryTest(unittest.TestCase):
    def test_accepts_successful_model_output_even_when_elapsed_exceeds_old_demo_target(self):
        from app.ai.model_runtime import ModelResult
        from app.ai.news_summary import summarize_news

        slow_success = ModelResult(
            ok=True,
            text="### Local AI News\n- Edge summary generated locally.",
            backend="ollama",
            model="qwen3:1.7b",
            elapsed_seconds=36.8,
        )
        items = [{"title": "Raspberry Pi edge AI summary runs locally", "link": "local://news", "source": "test", "timestamp": 1}]

        with patch("app.ai.news_summary.generate_ollama", return_value=slow_success):
            result = summarize_news(items, mode="ollama", model="qwen3:1.7b", timeout=30)

        self.assertEqual(result["backend"], "ollama")
        self.assertFalse(result["fallback"])
        self.assertEqual(result["elapsed_seconds"], 36.8)


if __name__ == "__main__":
    unittest.main()
