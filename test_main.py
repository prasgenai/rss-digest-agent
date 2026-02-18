import unittest
from unittest.mock import patch, MagicMock, mock_open
from datetime import datetime, timedelta
import json
import os

# Set dummy env vars before importing main (avoids Groq client init error)
os.environ.setdefault("GROQ_API_KEY", "test-key")
os.environ.setdefault("GMAIL_FROM", "test@gmail.com")
os.environ.setdefault("GMAIL_TO", "test@gmail.com")
os.environ.setdefault("GMAIL_APP_PASSWORD", "testpassword")

from main import (
    load_config,
    fetch_articles,
    filter_relevant_articles,
    summarize_articles,
    compile_digest,
    send_email,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_article(title="Test Article", score=8, with_bullets=False):
    article = {
        "title": title,
        "link": "https://example.com/article",
        "summary": "This is a test summary about AI in banking.",
        "published": "2026-02-18",
        "source": "Test Source",
        "relevance_score": score,
    }
    if with_bullets:
        article["bullets"] = "• Point one\n• Point two\n• Point three"
    return article


def make_groq_response(content):
    """Build a minimal mock Groq API response."""
    choice = MagicMock()
    choice.message.content = content
    response = MagicMock()
    response.choices = [choice]
    return response


# ---------------------------------------------------------------------------
# 1. load_config
# ---------------------------------------------------------------------------

class TestLoadConfig(unittest.TestCase):

    def test_loads_topics_and_feeds(self):
        yaml_content = "topics:\n  - AI in Finance\nfeeds:\n  - https://example.com/rss\n"
        with patch("builtins.open", mock_open(read_data=yaml_content)):
            config = load_config("config.yaml")
        self.assertIn("topics", config)
        self.assertIn("feeds", config)
        self.assertEqual(config["topics"], ["AI in Finance"])
        self.assertEqual(config["feeds"], ["https://example.com/rss"])

    def test_raises_if_file_missing(self):
        with self.assertRaises(FileNotFoundError):
            load_config("nonexistent_file.yaml")


# ---------------------------------------------------------------------------
# 2. fetch_articles
# ---------------------------------------------------------------------------

class TestFetchArticles(unittest.TestCase):

    def _make_feed(self, title, published_parsed=None, summary="A summary"):
        entry = MagicMock()
        entry.get = lambda key, default="": {
            "title": title,
            "link": "https://example.com",
            "summary": summary,
        }.get(key, default)
        entry.published_parsed = published_parsed
        feed_obj = MagicMock()
        feed_obj.entries = [entry]
        feed_obj.feed.get = lambda key, default="": {"title": "Source"}.get(key, default)
        return feed_obj

    @patch("main.feedparser.parse")
    def test_recent_article_included(self, mock_parse):
        recent = datetime.now() - timedelta(hours=2)
        mock_parse.return_value = self._make_feed(
            "Recent AI Article",
            published_parsed=recent.timetuple()[:9]
        )
        articles = fetch_articles(["https://example.com/rss"])
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["title"], "Recent AI Article")

    @patch("main.feedparser.parse")
    def test_old_article_excluded(self, mock_parse):
        old = datetime.now() - timedelta(hours=48)
        mock_parse.return_value = self._make_feed(
            "Old Article",
            published_parsed=old.timetuple()[:9]
        )
        articles = fetch_articles(["https://example.com/rss"])
        self.assertEqual(len(articles), 0)

    @patch("main.feedparser.parse")
    def test_article_with_no_date_included(self, mock_parse):
        entry = MagicMock()
        entry.get = lambda key, default="": {
            "title": "Undated Article",
            "link": "https://example.com",
            "summary": "No date available",
        }.get(key, default)
        entry.published_parsed = None
        feed_obj = MagicMock()
        feed_obj.entries = [entry]
        feed_obj.feed.get = lambda key, default="": "Source"
        mock_parse.return_value = feed_obj

        articles = fetch_articles(["https://example.com/rss"])
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["published"], "Unknown")

    @patch("main.feedparser.parse", side_effect=Exception("Network error"))
    def test_failing_feed_does_not_crash(self, mock_parse):
        # Should not raise; should return empty list
        articles = fetch_articles(["https://bad-feed.com/rss"])
        self.assertEqual(articles, [])

    @patch("main.feedparser.parse")
    def test_summary_truncated_to_500_chars(self, mock_parse):
        long_summary = "x" * 1000
        mock_parse.return_value = self._make_feed("Title", summary=long_summary)
        articles = fetch_articles(["https://example.com/rss"])
        self.assertLessEqual(len(articles[0]["summary"]), 500)


# ---------------------------------------------------------------------------
# 3. filter_relevant_articles
# ---------------------------------------------------------------------------

class TestFilterRelevantArticles(unittest.TestCase):

    def test_returns_empty_for_no_articles(self):
        result = filter_relevant_articles([], ["AI in Finance"])
        self.assertEqual(result, [])

    @patch("main.time.sleep")
    @patch("main.client")
    def test_relevant_article_passes_filter(self, mock_client, mock_sleep):
        mock_client.chat.completions.create.return_value = make_groq_response(
            '[{"id": 1, "score": 9, "relevant": true}]'
        )
        articles = [make_article("AI Fraud Detection in Banks")]
        result = filter_relevant_articles(articles, ["AI in Finance"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["relevance_score"], 9)

    @patch("main.time.sleep")
    @patch("main.client")
    def test_low_score_article_filtered_out(self, mock_client, mock_sleep):
        mock_client.chat.completions.create.return_value = make_groq_response(
            '[{"id": 1, "score": 4, "relevant": false}]'
        )
        articles = [make_article("Sports News Today")]
        result = filter_relevant_articles(articles, ["AI in Finance"])
        self.assertEqual(len(result), 0)

    @patch("main.time.sleep")
    @patch("main.client")
    def test_results_sorted_by_score_descending(self, mock_client, mock_sleep):
        mock_client.chat.completions.create.return_value = make_groq_response(
            '[{"id": 1, "score": 7, "relevant": true}, {"id": 2, "score": 10, "relevant": true}]'
        )
        articles = [make_article("Article A"), make_article("Article B")]
        result = filter_relevant_articles(articles, ["AI in Finance"])
        self.assertEqual(len(result), 2)
        self.assertGreaterEqual(result[0]["relevance_score"], result[1]["relevance_score"])

    @patch("main.time.sleep")
    @patch("main.client")
    def test_capped_at_12_articles(self, mock_client, mock_sleep):
        # All 15 articles score 8 (relevant)
        groq_responses = [
            '[{"id": 1, "score": 8, "relevant": true}, {"id": 2, "score": 8, "relevant": true}, '
            '{"id": 3, "score": 8, "relevant": true}, {"id": 4, "score": 8, "relevant": true}, '
            '{"id": 5, "score": 8, "relevant": true}]'
        ]
        mock_client.chat.completions.create.return_value = make_groq_response(groq_responses[0])
        articles = [make_article(f"Article {i}") for i in range(15)]
        result = filter_relevant_articles(articles, ["AI in Finance"])
        self.assertLessEqual(len(result), 12)

    @patch("main.time.sleep")
    @patch("main.client")
    def test_groq_error_handled_gracefully(self, mock_client, mock_sleep):
        mock_client.chat.completions.create.side_effect = Exception("API error")
        articles = [make_article("Some Article")]
        # Should not raise; returns empty list
        result = filter_relevant_articles(articles, ["AI in Finance"])
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# 4. summarize_articles
# ---------------------------------------------------------------------------

class TestSummarizeArticles(unittest.TestCase):

    def test_returns_empty_for_no_articles(self):
        result = summarize_articles([])
        self.assertEqual(result, [])

    @patch("main.time.sleep")
    @patch("main.client")
    def test_bullets_added_to_article(self, mock_client, mock_sleep):
        mock_client.chat.completions.create.return_value = make_groq_response(
            "[1]\n• AI helps banks detect fraud faster\n• Risk scores improve 40%\n• Compliance costs reduced"
        )
        articles = [make_article()]
        result = summarize_articles(articles)
        self.assertIn("bullets", result[0])
        self.assertIn("•", result[0]["bullets"])

    @patch("main.time.sleep")
    @patch("main.client")
    def test_fallback_on_groq_error(self, mock_client, mock_sleep):
        mock_client.chat.completions.create.side_effect = Exception("API error")
        articles = [make_article()]
        result = summarize_articles(articles)
        # Should fall back to raw summary snippet
        self.assertIn("bullets", result[0])
        self.assertTrue(result[0]["bullets"].startswith("•"))

    @patch("main.time.sleep")
    @patch("main.client")
    def test_multiple_articles_all_get_bullets(self, mock_client, mock_sleep):
        mock_client.chat.completions.create.return_value = make_groq_response(
            "[1]\n• Point A\n• Point B\n• Point C\n[2]\n• Point D\n• Point E\n• Point F"
        )
        articles = [make_article("Article 1"), make_article("Article 2")]
        result = summarize_articles(articles)
        for article in result:
            self.assertIn("bullets", article)


# ---------------------------------------------------------------------------
# 5. compile_digest
# ---------------------------------------------------------------------------

class TestCompileDigest(unittest.TestCase):

    def test_returns_html_string(self):
        articles = [make_article(with_bullets=True)]
        html = compile_digest(articles, ["AI in Finance"])
        self.assertIsInstance(html, str)
        self.assertIn("<html>", html)
        self.assertIn("</html>", html)

    def test_article_title_appears_in_output(self):
        articles = [make_article(title="AI Fraud Detection", with_bullets=True)]
        html = compile_digest(articles, ["AI in Finance"])
        self.assertIn("AI Fraud Detection", html)

    def test_article_count_in_header(self):
        articles = [make_article(with_bullets=True), make_article(with_bullets=True)]
        html = compile_digest(articles, ["AI in Finance"])
        self.assertIn("2 articles found", html)

    def test_empty_articles_shows_no_results_message(self):
        html = compile_digest([], ["AI in Finance"])
        self.assertIn("No relevant articles found today", html)

    def test_high_score_uses_green_color(self):
        articles = [make_article(score=9, with_bullets=True)]
        html = compile_digest(articles, ["AI in Finance"])
        self.assertIn("#28a745", html)

    def test_medium_score_uses_blue_color(self):
        articles = [make_article(score=7, with_bullets=True)]
        html = compile_digest(articles, ["AI in Finance"])
        self.assertIn("#4a90d9", html)

    def test_topic_appears_in_output(self):
        articles = [make_article(with_bullets=True)]
        html = compile_digest(articles, ["AI in Finance"])
        self.assertIn("AI in Finance", html)

    def test_article_link_is_clickable(self):
        articles = [make_article(with_bullets=True)]
        html = compile_digest(articles, ["AI in Finance"])
        self.assertIn('href="https://example.com/article"', html)


# ---------------------------------------------------------------------------
# 6. send_email
# ---------------------------------------------------------------------------

class TestSendEmail(unittest.TestCase):

    @patch("main.smtplib.SMTP_SSL")
    def test_email_sent_with_correct_credentials(self, mock_smtp_class):
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        send_email(
            html_content="<html><body>Test</body></html>",
            subject="Test Digest",
            from_email="sender@gmail.com",
            to_email="receiver@gmail.com",
            app_password="testpassword",
        )

        mock_server.login.assert_called_once_with("sender@gmail.com", "testpassword")
        mock_server.sendmail.assert_called_once()
        args = mock_server.sendmail.call_args[0]
        self.assertEqual(args[0], "sender@gmail.com")
        self.assertEqual(args[1], ["receiver@gmail.com"])

    @patch("main.smtplib.SMTP_SSL")
    def test_uses_ssl_on_port_465(self, mock_smtp_class):
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        send_email("<html></html>", "Subject", "a@gmail.com", "b@gmail.com", "pwd")

        mock_smtp_class.assert_called_once_with("smtp.gmail.com", 465)

    @patch("main.smtplib.SMTP_SSL")
    def test_comma_separated_recipients(self, mock_smtp_class):
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        send_email("<html></html>", "Subject", "a@gmail.com", "b@gmail.com,c@gmail.com", "pwd")

        args = mock_server.sendmail.call_args[0]
        self.assertIn("b@gmail.com", args[1])
        self.assertIn("c@gmail.com", args[1])

    @patch("main.smtplib.SMTP_SSL")
    def test_semicolon_separated_recipients(self, mock_smtp_class):
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        send_email("<html></html>", "Subject", "a@gmail.com", "b@gmail.com;c@gmail.com;d@gmail.com", "pwd")

        args = mock_server.sendmail.call_args[0]
        self.assertIn("b@gmail.com", args[1])
        self.assertIn("c@gmail.com", args[1])
        self.assertIn("d@gmail.com", args[1])

    @patch("main.smtplib.SMTP_SSL")
    def test_whitespace_around_recipients_handled(self, mock_smtp_class):
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        send_email("<html></html>", "Subject", "a@gmail.com", " b@gmail.com , c@gmail.com ", "pwd")

        args = mock_server.sendmail.call_args[0]
        self.assertIn("b@gmail.com", args[1])
        self.assertIn("c@gmail.com", args[1])

    @patch("main.smtplib.SMTP_SSL")
    def test_single_recipient_still_works(self, mock_smtp_class):
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        send_email("<html></html>", "Subject", "a@gmail.com", "b@gmail.com", "pwd")

        args = mock_server.sendmail.call_args[0]
        self.assertEqual(args[1], ["b@gmail.com"])


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
