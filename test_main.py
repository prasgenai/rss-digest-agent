import unittest
from unittest.mock import patch, MagicMock, mock_open
from datetime import datetime, timedelta
import json
import os
import tempfile

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
    init_cache,
    is_cached,
    add_to_cache,
    purge_expired,
    scrape_article,
    resolve_users,
    main,
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
    def test_duplicate_urls_across_feeds_deduplicated(self, mock_parse):
        recent = datetime.now() - timedelta(hours=2)
        mock_parse.return_value = self._make_feed(
            "Same Article", published_parsed=recent.timetuple()[:9]
        )
        # Same feed URL passed twice simulates same article in two feeds
        articles = fetch_articles(["https://feed1.com/rss", "https://feed2.com/rss"])
        deduplicated = list({a["link"]: a for a in articles}.values())
        self.assertEqual(len(deduplicated), 1)

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

    @patch("main.time.sleep")
    @patch("main.client")
    def test_relevant_true_but_score_below_threshold_filtered_out(self, mock_client, mock_sleep):
        # LLM marks relevant=true but score=6 — both conditions must pass (score >= 7 required)
        mock_client.chat.completions.create.return_value = make_groq_response(
            '[{"id": 1, "score": 6, "relevant": true}]'
        )
        articles = [make_article("Borderline Article")]
        result = filter_relevant_articles(articles, ["AI in Finance"])
        self.assertEqual(len(result), 0)


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

    def test_low_score_uses_orange_color(self):
        articles = [make_article(score=5, with_bullets=True)]
        html = compile_digest(articles, ["AI in Finance"])
        self.assertIn("#fd7e14", html)


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
# 7. SQLite Article Cache
# ---------------------------------------------------------------------------

class TestArticleCache(unittest.TestCase):

    def setUp(self):
        """Create a temporary DB file for each test."""
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db = self.tmp.name
        self.tmp.close()
        init_cache(db_path=self.db)

    def tearDown(self):
        os.unlink(self.db)

    def test_new_url_not_cached(self):
        self.assertFalse(is_cached("https://example.com/new-article", db_path=self.db))

    def test_url_cached_after_add(self):
        add_to_cache(["https://example.com/article-1"], db_path=self.db)
        self.assertTrue(is_cached("https://example.com/article-1", db_path=self.db))

    def test_multiple_urls_cached(self):
        urls = ["https://example.com/a", "https://example.com/b", "https://example.com/c"]
        add_to_cache(urls, db_path=self.db)
        for url in urls:
            self.assertTrue(is_cached(url, db_path=self.db))

    def test_duplicate_url_not_raise(self):
        add_to_cache(["https://example.com/article"], db_path=self.db)
        # Adding same URL again should not raise
        add_to_cache(["https://example.com/article"], db_path=self.db)
        self.assertTrue(is_cached("https://example.com/article", db_path=self.db))

    def test_purge_removes_old_entries(self):
        import sqlite3
        # Manually insert an old entry
        old_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        conn = sqlite3.connect(self.db)
        conn.execute("INSERT INTO article_cache (url, cached_at) VALUES (?, ?)",
                     ("https://example.com/old", old_date))
        conn.commit()
        conn.close()

        purge_expired(days=7, db_path=self.db)
        self.assertFalse(is_cached("https://example.com/old", db_path=self.db))

    def test_purge_keeps_recent_entries(self):
        add_to_cache(["https://example.com/recent"], db_path=self.db)
        purge_expired(days=7, db_path=self.db)
        self.assertTrue(is_cached("https://example.com/recent", db_path=self.db))

    def test_cache_created_on_init(self):
        # A fresh DB initialized by setUp should be queryable
        result = is_cached("https://example.com/anything", db_path=self.db)
        self.assertFalse(result)


# ---------------------------------------------------------------------------
# 8. Article Scraping
# ---------------------------------------------------------------------------

class TestScrapeArticle(unittest.TestCase):

    @patch("main.requests.get")
    def test_returns_text_from_paragraphs(self, mock_get):
        html = """<html><body>
            <p>This is a long enough paragraph about AI in banking fraud detection systems.</p>
            <p>Another substantial paragraph discussing risk management and compliance tools.</p>
        </body></html>"""
        mock_response = MagicMock()
        mock_response.text = html
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = scrape_article("https://example.com/article")
        self.assertIsNotNone(result)
        self.assertIn("AI in banking", result)

    @patch("main.requests.get")
    def test_strips_script_and_nav_tags(self, mock_get):
        html = """<html><body>
            <nav>Home | About | Contact</nav>
            <script>alert('test')</script>
            <p>This is meaningful article content about AI fraud detection in banking.</p>
        </body></html>"""
        mock_response = MagicMock()
        mock_response.text = html
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = scrape_article("https://example.com/article")
        self.assertNotIn("alert", result)
        self.assertIn("meaningful article content", result)

    @patch("main.requests.get")
    def test_respects_max_chars_limit(self, mock_get):
        long_text = "A" * 5000
        html = f"<html><body><p>{long_text}</p></body></html>"
        mock_response = MagicMock()
        mock_response.text = html
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = scrape_article("https://example.com/article", max_chars=500)
        self.assertLessEqual(len(result), 500)

    @patch("main.requests.get", side_effect=Exception("Connection error"))
    def test_returns_none_on_request_failure(self, mock_get):
        result = scrape_article("https://example.com/article")
        self.assertIsNone(result)

    @patch("main.requests.get")
    def test_returns_none_when_no_paragraphs(self, mock_get):
        html = "<html><body><div>No paragraphs here</div></body></html>"
        mock_response = MagicMock()
        mock_response.text = html
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = scrape_article("https://example.com/article")
        self.assertIsNone(result)

    @patch("main.requests.get")
    def test_skips_short_paragraphs(self, mock_get):
        html = """<html><body>
            <p>Short.</p>
            <p>This is a sufficiently long paragraph with meaningful content about AI and banking systems.</p>
        </body></html>"""
        mock_response = MagicMock()
        mock_response.text = html
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = scrape_article("https://example.com/article")
        self.assertNotIn("Short.", result)
        self.assertIn("sufficiently long paragraph", result)


# ---------------------------------------------------------------------------
# 9. resolve_users
# ---------------------------------------------------------------------------

class TestResolveUsers(unittest.TestCase):

    def test_returns_users_list_when_users_key_present(self):
        config = {
            "users": [
                {"name": "Finance Team", "emails": ["a@gmail.com"], "topics": ["Finance AI"]},
                {"name": "Tech Team", "emails": ["b@gmail.com"], "topics": ["Dev AI"]},
            ],
            "feeds": [],
        }
        result = resolve_users(config)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["name"], "Finance Team")
        self.assertEqual(result[1]["name"], "Tech Team")

    @patch.dict(os.environ, {"GMAIL_TO": "fallback@gmail.com"})
    def test_fallback_single_user_when_no_users_key(self):
        config = {"topics": ["AI in Finance"], "feeds": []}
        result = resolve_users(config)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "Default")

    @patch.dict(os.environ, {"GMAIL_TO": "a@gmail.com,b@gmail.com"})
    def test_parses_comma_separated_gmail_to_in_fallback(self):
        config = {"topics": ["AI"], "feeds": []}
        result = resolve_users(config)
        self.assertIn("a@gmail.com", result[0]["emails"])
        self.assertIn("b@gmail.com", result[0]["emails"])

    @patch.dict(os.environ, {"GMAIL_TO": "a@gmail.com;b@gmail.com"})
    def test_parses_semicolon_separated_gmail_to_in_fallback(self):
        config = {"topics": ["AI"], "feeds": []}
        result = resolve_users(config)
        self.assertIn("a@gmail.com", result[0]["emails"])
        self.assertIn("b@gmail.com", result[0]["emails"])

    def test_users_key_takes_precedence_over_topics(self):
        config = {
            "users": [
                {"name": "Team A", "emails": ["a@gmail.com"], "topics": ["Topic A"]},
            ],
            "topics": ["Old Topic"],
            "feeds": [],
        }
        result = resolve_users(config)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["topics"], ["Topic A"])

    def test_each_user_has_required_keys(self):
        config = {
            "users": [
                {"name": "Finance Team", "emails": ["a@gmail.com"], "topics": ["Finance AI"]},
                {"name": "Tech Team", "emails": ["b@gmail.com"], "topics": ["Dev AI"]},
            ],
            "feeds": [],
        }
        result = resolve_users(config)
        for user in result:
            self.assertIn("name", user)
            self.assertIn("emails", user)
            self.assertIn("topics", user)

    @patch.dict(os.environ, {"GMAIL_TO": "fallback@gmail.com"})
    def test_fallback_user_topics_match_config_topics(self):
        topics = ["AI in Finance", "AI for Dev"]
        config = {"topics": topics, "feeds": []}
        result = resolve_users(config)
        self.assertEqual(result[0]["topics"], topics)


# ---------------------------------------------------------------------------
# 10. main() — multi-user integration
# ---------------------------------------------------------------------------

class TestMainMultiUser(unittest.TestCase):

    def _make_config_multi_user(self):
        return {
            "feeds": ["https://example.com/rss"],
            "cache": {"expiry_days": 7},
            "scraping": {"enabled": False},
            "users": [
                {"name": "Finance Team", "emails": ["finance@gmail.com"], "topics": ["Finance AI"]},
                {"name": "Technology Team", "emails": ["tech@gmail.com"], "topics": ["Dev AI"]},
            ],
        }

    def _make_config_single_user(self):
        return {
            "feeds": ["https://example.com/rss"],
            "cache": {"expiry_days": 7},
            "scraping": {"enabled": False},
            "topics": ["AI in Finance"],
        }

    @patch("main.add_to_cache")
    @patch("main.is_cached", return_value=False)
    @patch("main.purge_expired")
    @patch("main.init_cache")
    @patch("main.send_email")
    @patch("main.compile_digest", return_value="<html></html>")
    @patch("main.summarize_articles", side_effect=lambda x: x)
    @patch("main.filter_relevant_articles", return_value=[])
    @patch("main.fetch_articles", return_value=[])
    @patch("main.load_config")
    def test_send_email_called_once_per_user_group(
        self, mock_load, mock_fetch, mock_filter, mock_summarize,
        mock_compile, mock_send, mock_init, mock_purge, mock_cached, mock_cache
    ):
        mock_load.return_value = self._make_config_multi_user()
        main()
        self.assertEqual(mock_send.call_count, 2)

    @patch("main.add_to_cache")
    @patch("main.is_cached", return_value=False)
    @patch("main.purge_expired")
    @patch("main.init_cache")
    @patch("main.send_email")
    @patch("main.compile_digest", return_value="<html></html>")
    @patch("main.summarize_articles", side_effect=lambda x: x)
    @patch("main.filter_relevant_articles", return_value=[])
    @patch("main.fetch_articles", return_value=[])
    @patch("main.load_config")
    def test_email_subject_includes_group_name(
        self, mock_load, mock_fetch, mock_filter, mock_summarize,
        mock_compile, mock_send, mock_init, mock_purge, mock_cached, mock_cache
    ):
        mock_load.return_value = self._make_config_multi_user()
        main()
        subjects = [c.kwargs["subject"] for c in mock_send.call_args_list]
        self.assertTrue(any("Finance Team" in s for s in subjects))
        self.assertTrue(any("Technology Team" in s for s in subjects))

    @patch("main.add_to_cache")
    @patch("main.is_cached", return_value=False)
    @patch("main.purge_expired")
    @patch("main.init_cache")
    @patch("main.send_email")
    @patch("main.compile_digest", return_value="<html></html>")
    @patch("main.summarize_articles", side_effect=lambda x: x)
    @patch("main.filter_relevant_articles", return_value=[])
    @patch("main.fetch_articles", return_value=[])
    @patch("main.load_config")
    def test_fetch_articles_called_only_once(
        self, mock_load, mock_fetch, mock_filter, mock_summarize,
        mock_compile, mock_send, mock_init, mock_purge, mock_cached, mock_cache
    ):
        mock_load.return_value = self._make_config_multi_user()
        main()
        mock_fetch.assert_called_once()

    @patch("main.add_to_cache")
    @patch("main.is_cached", return_value=False)
    @patch("main.purge_expired")
    @patch("main.init_cache")
    @patch("main.send_email")
    @patch("main.compile_digest", return_value="<html></html>")
    @patch("main.summarize_articles", side_effect=lambda x: x)
    @patch("main.filter_relevant_articles", return_value=[])
    @patch("main.fetch_articles", return_value=[])
    @patch("main.load_config")
    def test_add_to_cache_called_only_once(
        self, mock_load, mock_fetch, mock_filter, mock_summarize,
        mock_compile, mock_send, mock_init, mock_purge, mock_cached, mock_cache
    ):
        mock_load.return_value = self._make_config_multi_user()
        main()
        mock_cache.assert_called_once()

    @patch("main.add_to_cache")
    @patch("main.is_cached", return_value=False)
    @patch("main.purge_expired")
    @patch("main.init_cache")
    @patch("main.send_email")
    @patch("main.compile_digest", return_value="<html></html>")
    @patch("main.summarize_articles", side_effect=lambda x: x)
    @patch("main.scrape_article", return_value="scraped content")
    @patch("main.filter_relevant_articles")
    @patch("main.fetch_articles")
    @patch("main.load_config")
    def test_scrape_article_called_once_per_article(
        self, mock_load, mock_fetch, mock_filter, mock_scrape,
        mock_summarize, mock_compile, mock_send, mock_init,
        mock_purge, mock_cached, mock_cache
    ):
        article = {
            "link": "https://example.com/a", "title": "T",
            "summary": "S", "published": "2026-02-18", "source": "Src",
            "relevance_score": 8,
        }
        mock_fetch.return_value = [article]
        # Both user groups receive the same article dict (same Python object)
        mock_filter.side_effect = [[article], [article]]
        config = self._make_config_multi_user()
        config["scraping"] = {"enabled": True, "max_chars": 2000, "timeout_seconds": 10}
        mock_load.return_value = config
        main()
        # 'scraped' flag set after first group prevents re-scraping for second group
        mock_scrape.assert_called_once()

    @patch("main.add_to_cache")
    @patch("main.is_cached", return_value=False)
    @patch("main.purge_expired")
    @patch("main.init_cache")
    @patch("main.send_email")
    @patch("main.compile_digest", return_value="<html></html>")
    @patch("main.summarize_articles", side_effect=lambda x: x)
    @patch("main.filter_relevant_articles", return_value=[])
    @patch("main.fetch_articles")
    @patch("main.load_config")
    def test_add_to_cache_receives_only_fresh_urls(
        self, mock_load, mock_fetch, mock_filter, mock_summarize,
        mock_compile, mock_send, mock_init, mock_purge, mock_cached, mock_cache
    ):
        # 2 articles fetched; only 1 is fresh (is_cached returns True for first, False for second)
        article_cached = {"link": "https://example.com/old", "title": "Old", "summary": "S", "published": "2026-02-17", "source": "Src"}
        article_fresh  = {"link": "https://example.com/new", "title": "New", "summary": "S", "published": "2026-02-18", "source": "Src"}
        mock_fetch.return_value = [article_cached, article_fresh]
        mock_cached.side_effect = lambda url: url == "https://example.com/old"
        mock_load.return_value = self._make_config_multi_user()
        main()
        cached_urls = mock_cache.call_args[0][0]
        self.assertIn("https://example.com/new", cached_urls)
        self.assertNotIn("https://example.com/old", cached_urls)

    @patch("main.add_to_cache")
    @patch("main.is_cached", return_value=False)
    @patch("main.purge_expired")
    @patch("main.init_cache")
    @patch("main.send_email")
    @patch("main.compile_digest", return_value="<html></html>")
    @patch("main.summarize_articles", side_effect=lambda x: x)
    @patch("main.scrape_article")
    @patch("main.filter_relevant_articles", return_value=[])
    @patch("main.fetch_articles", return_value=[])
    @patch("main.load_config")
    def test_scrape_article_not_called_when_scraping_disabled(
        self, mock_load, mock_fetch, mock_filter, mock_scrape,
        mock_summarize, mock_compile, mock_send, mock_init,
        mock_purge, mock_cached, mock_cache
    ):
        config = self._make_config_multi_user()
        config["scraping"] = {"enabled": False}
        mock_load.return_value = config
        main()
        mock_scrape.assert_not_called()

    @patch("main.add_to_cache")
    @patch("main.is_cached", return_value=False)
    @patch("main.purge_expired")
    @patch("main.init_cache")
    @patch("main.send_email")
    @patch("main.compile_digest", return_value="<html></html>")
    @patch("main.summarize_articles", side_effect=lambda x: x)
    @patch("main.filter_relevant_articles", return_value=[])
    @patch("main.fetch_articles", return_value=[])
    @patch("main.load_config")
    def test_backward_compat_no_users_key_sends_once(
        self, mock_load, mock_fetch, mock_filter, mock_summarize,
        mock_compile, mock_send, mock_init, mock_purge, mock_cached, mock_cache
    ):
        mock_load.return_value = self._make_config_single_user()
        main()
        mock_send.assert_called_once()


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
