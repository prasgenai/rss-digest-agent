import os
import json
import time
import re
import smtplib
import sqlite3
import html as html_lib
import feedparser
import requests
import yaml
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
from groq import Groq

load_dotenv()
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

CACHE_DB = "digest_cache.db"
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def init_cache(db_path=None):
    """Create the SQLite cache DB and table if they don't exist."""
    path = db_path or CACHE_DB
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS article_cache (
            url TEXT PRIMARY KEY,
            cached_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def is_cached(url, db_path=None):
    """Return True if the article URL has already been processed."""
    path = db_path or CACHE_DB
    conn = sqlite3.connect(path)
    row = conn.execute("SELECT url FROM article_cache WHERE url = ?", (url,)).fetchone()
    conn.close()
    return row is not None


def add_to_cache(urls, db_path=None):
    """Add a list of article URLs to the cache."""
    path = db_path or CACHE_DB
    today = datetime.now().strftime("%Y-%m-%d")
    conn = sqlite3.connect(path)
    conn.executemany(
        "INSERT OR IGNORE INTO article_cache (url, cached_at) VALUES (?, ?)",
        [(url, today) for url in urls],
    )
    conn.commit()
    conn.close()


def purge_expired(days=7, db_path=None):
    """Remove cache entries older than `days` days."""
    path = db_path or CACHE_DB
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    conn = sqlite3.connect(path)
    conn.execute("DELETE FROM article_cache WHERE cached_at < ?", (cutoff,))
    conn.commit()
    conn.close()


def scrape_article(url, max_chars=2000, timeout=10):
    """Fetch full article text from URL. Returns None if scraping fails."""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; RSSDigestAgent/1.0)"}
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        # Remove non-content tags
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        # Extract meaningful paragraphs (skip short ones like nav labels)
        paragraphs = soup.find_all("p")
        text = " ".join(
            p.get_text(strip=True)
            for p in paragraphs
            if len(p.get_text(strip=True)) > 50
        )

        return text[:max_chars] if text else None
    except Exception as e:
        print(f"  Warning: Could not scrape {url}: {type(e).__name__}")
        return None


def load_config(path=None):
    """Load YAML config. Prefers config.local.yaml (gitignored, user-editable)
    over config.yaml (version-controlled template) when no path is given.
    """
    if path is None:
        local = os.path.join(_BASE_DIR, "config.local.yaml")
        path = local if os.path.exists(local) else os.path.join(_BASE_DIR, "config.yaml")
    with open(path) as f:
        return yaml.safe_load(f)


def validate_config(config):
    """Raise ValueError early if required config keys are missing or empty."""
    if not config.get("feeds"):
        raise ValueError("Config error: 'feeds' key is missing or empty — add at least one RSS feed URL")
    if "users" not in config and "topics" not in config:
        raise ValueError("Config error: must have either 'users' or 'topics' key")


def group_name_to_env_key(name):
    """Derive env var key from a user group name.

    Examples:
        'Finance Team'     -> 'FINANCE_TEAM_EMAILS'
        'A-Level Students' -> 'A_LEVEL_STUDENTS_EMAILS'
    """
    return re.sub(r"[^A-Z0-9]", "_", name.upper()) + "_EMAILS"


def resolve_users(config):
    """Return list of user dicts from config.
    Multi-user mode: uses config['users'], with emails read from env vars.
    Single-user fallback: builds one user from config['topics'] + GMAIL_TO env var.
    """
    if "users" in config:
        users = []
        for user in config["users"]:
            env_key = group_name_to_env_key(user["name"])
            emails_str = os.getenv(env_key, "")
            emails = [e.strip() for e in re.split(r"[,;]", emails_str) if e.strip()]
            users.append({"name": user["name"], "emails": emails, "topics": user["topics"]})
        return users
    gmail_to = os.getenv("GMAIL_TO", "")
    return [{
        "name": "Default",
        "emails": [e.strip() for e in re.split(r"[,;]", gmail_to) if e.strip()],
        "topics": config["topics"],
    }]


def fetch_articles(feeds, hours=24):
    """Fetch articles from RSS feeds published in the last `hours` hours."""
    articles = []
    cutoff = datetime.now() - timedelta(hours=hours)

    for feed_url in feeds:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries:
                published = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    try:
                        published = datetime(*entry.published_parsed[:6])
                    except Exception:
                        pass

                # Include if recent or if we can't determine the date
                if published is None or published >= cutoff:
                    articles.append({
                        "title": entry.get("title", "No title"),
                        "link": entry.get("link", ""),
                        "summary": entry.get("summary", entry.get("description", ""))[:500],
                        "published": published.strftime("%Y-%m-%d") if published else "Unknown",
                        "source": feed.feed.get("title", feed_url),
                    })
        except Exception as e:
            print(f"  Warning: Could not fetch {feed_url}: {e}")

    return articles


def filter_relevant_articles(articles, topics):
    """Use Groq LLM to filter articles relevant to our topics (batched)."""
    if not articles:
        return []

    relevant = []
    topics_str = "\n".join(f"- {t}" for t in topics)
    batch_size = 5

    for i in range(0, len(articles), batch_size):
        batch = articles[i:i + batch_size]
        articles_text = ""
        for j, article in enumerate(batch, 1):
            articles_text += f"[{j}] Title: {article['title']}\nSummary: {article['summary'][:200]}\n\n"

        prompt = f"""You are a content filter for a professional research digest.

Topics of interest:
{topics_str}

For each article below, decide if it is relevant to ANY of the topics above.
Return ONLY a valid JSON array (no extra text):
[{{"id": 1, "score": 8, "relevant": true}}, {{"id": 2, "score": 3, "relevant": false}}, ...]

Score 1-10 (7+ = relevant). Articles:
{articles_text}"""

        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=300,
            )
            result_text = response.choices[0].message.content.strip()
            match = re.search(r"\[.*\]", result_text, re.DOTALL)
            if match:
                results = json.loads(match.group())
                for result in results:
                    idx = result.get("id", 0) - 1
                    if 0 <= idx < len(batch) and result.get("relevant") and result.get("score", 0) >= 7:
                        batch[idx]["relevance_score"] = result["score"]
                        relevant.append(batch[idx])
        except Exception as e:
            print(f"  Warning: Filter error on batch {i // batch_size + 1}: {e}")

        time.sleep(1)  # Stay within Groq rate limits

    relevant.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
    return relevant[:12]  # Cap at 12 articles per digest


def summarize_articles(articles, topics):
    """Summarize each relevant article into 3 bullet points (batched)."""
    if not articles:
        return []

    batch_size = 5
    topics_str = "\n".join(f"- {t}" for t in topics)

    for i in range(0, len(articles), batch_size):
        batch = articles[i:i + batch_size]
        articles_text = ""
        for j, article in enumerate(batch, 1):
            articles_text += f"[{j}] Title: {article['title']}\nContent: {article['summary']}\n\n"

        prompt = f"""Summarize each article in exactly 3 concise bullet points.
Focus on insights relevant to these topics:
{topics_str}

{articles_text}
Format EXACTLY as (no extra text before [1]):
[1]
• First key point
• Second key point
• Third key point
[2]
• First key point
...and so on"""

        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=1500,
            )
            summaries_text = response.choices[0].message.content.strip()
            sections = re.split(r"\[(\d+)\]", summaries_text)
            summaries = {}
            for k in range(1, len(sections), 2):
                idx = int(sections[k])
                content = sections[k + 1].strip() if k + 1 < len(sections) else ""
                summaries[idx] = content

            for j, article in enumerate(batch, 1):
                article["bullets"] = summaries.get(j, f"• {article['summary'][:200]}")

        except Exception as e:
            print(f"  Warning: Summarize error on batch {i // batch_size + 1}: {e}")
            for article in batch:
                article["bullets"] = f"• {article['summary'][:200]}"

        time.sleep(1)

    return articles


def analyze_sentiment(articles):
    """Classify each article as Positive, Negative, or Neutral using Groq LLM (batched)."""
    if not articles:
        return []

    batch_size = 5

    for i in range(0, len(articles), batch_size):
        batch = articles[i:i + batch_size]
        articles_text = ""
        for j, article in enumerate(batch, 1):
            content = article.get("bullets", article["summary"])[:300]
            articles_text += f"[{j}] Title: {article['title']}\nContent: {content}\n\n"

        prompt = f"""Analyze the sentiment of each article.
Classify each as Positive, Negative, or Neutral based on its implications for the intended audience.
Return ONLY a valid JSON array (no extra text):
[{{"id": 1, "sentiment": "Positive"}}, {{"id": 2, "sentiment": "Negative"}}, ...]

Sentiment must be exactly one of: "Positive", "Negative", "Neutral". Articles:
{articles_text}"""

        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=200,
            )
            result_text = response.choices[0].message.content.strip()
            match = re.search(r"\[.*\]", result_text, re.DOTALL)
            if match:
                results = json.loads(match.group())
                for result in results:
                    idx = result.get("id", 0) - 1
                    if 0 <= idx < len(batch):
                        sentiment = result.get("sentiment", "Neutral")
                        if sentiment not in ("Positive", "Negative", "Neutral"):
                            sentiment = "Neutral"
                        batch[idx]["sentiment"] = sentiment
        except Exception as e:
            print(f"  Warning: Sentiment error on batch {i // batch_size + 1}: {e}")
            for article in batch:
                article.setdefault("sentiment", "Neutral")

        time.sleep(1)

    return articles


def compile_digest(articles, topics):
    """Compile an HTML email digest."""
    today = datetime.now().strftime("%B %d, %Y")
    topics_display = " &nbsp;|&nbsp; ".join(topics)

    html = f"""<html>
<body style="font-family: Arial, sans-serif; max-width: 720px; margin: 0 auto; padding: 20px; color: #333; background: #fff;">
  <div style="background: #1a1a2e; padding: 25px; border-radius: 8px; margin-bottom: 20px;">
    <h1 style="color: #fff; margin: 0; font-size: 24px;">AI Research Digest</h1>
    <p style="color: #aac4e8; margin: 8px 0 0 0; font-size: 14px;">{today} &nbsp;·&nbsp; {len(articles)} articles found</p>
  </div>
  <p style="color: #666; font-size: 13px; padding: 0 5px;">Topics: <em>{topics_display}</em></p>
  <hr style="border: none; border-top: 1px solid #eee; margin: 15px 0;">
"""

    if not articles:
        html += '<p style="padding: 20px; color: #888;">No relevant articles found today. Check back tomorrow!</p>'
    else:
        sentiment_colors = {"Positive": "#28a745", "Negative": "#dc3545", "Neutral": "#6c757d"}
        for article in articles:
            score = article.get("relevance_score", 0)
            bar_color = "#28a745" if score >= 9 else "#4a90d9" if score >= 7 else "#fd7e14"
            bullets_html = article.get("bullets", "").replace("\n", "<br>").replace("•", "&#8226;")
            sentiment = article.get("sentiment", "")
            sentiment_html = ""
            if sentiment:
                color = sentiment_colors.get(sentiment, "#6c757d")
                sentiment_html = f' &nbsp;·&nbsp; <span style="color: {color}; font-weight: bold;">&#9679; {sentiment}</span>'
            safe_title = html_lib.escape(article['title'])
            safe_link = article['link'] if not article['link'].lower().startswith("javascript:") else "#"
            html += f"""  <div style="margin: 20px 0; padding: 18px; border-left: 4px solid {bar_color}; background: #f8f9fa; border-radius: 0 6px 6px 0;">
    <h3 style="margin: 0 0 6px 0; font-size: 16px; line-height: 1.4;">
      <a href="{safe_link}" style="color: #1a1a2e; text-decoration: none;">{safe_title}</a>
    </h3>
    <p style="color: #999; font-size: 12px; margin: 0 0 10px 0;">
      {article['source']} &nbsp;·&nbsp; {article['published']} &nbsp;·&nbsp; Relevance: {score}/10{sentiment_html}
    </p>
    <div style="font-size: 14px; line-height: 1.7; color: #444;">
      {bullets_html}
    </div>
  </div>
"""

    html += """  <hr style="border: none; border-top: 1px solid #eee; margin-top: 30px;">
  <p style="color: #bbb; font-size: 11px; text-align: center; padding: 10px 0;">
    Generated by RSS Research Digest Agent &nbsp;·&nbsp; Powered by Groq + Llama 3.3
  </p>
</body>
</html>"""

    return html


def send_email(html_content, subject, from_email, to_email, app_password):
    """Send HTML email via Gmail SMTP.

    to_email supports multiple addresses separated by comma or semicolon.
    Example: 'a@gmail.com,b@gmail.com' or 'a@gmail.com;b@gmail.com'
    """
    recipients = [r.strip() for r in re.split(r"[,;]", to_email) if r.strip()]
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html_content, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(from_email, app_password)
        server.sendmail(from_email, recipients, msg.as_string())


def main():
    config = load_config()
    validate_config(config)
    init_cache()
    purge_expired(days=config.get("cache", {}).get("expiry_days", 7))

    # Shared: fetch once for all users
    print("Step 1: Fetching articles from RSS feeds...")
    fetch_cfg = config.get("fetch", {})
    articles = fetch_articles(config.get("feeds", []), hours=fetch_cfg.get("lookback_hours", 24))
    articles = list({a["link"]: a for a in articles}.values())
    print(f"  Found {len(articles)} unique articles")

    fresh = [a for a in articles if not is_cached(a["link"])]
    print(f"  {len(fresh)} new (skipped {len(articles) - len(fresh)} already seen)")

    users = resolve_users(config)
    today = datetime.now().strftime("%Y-%m-%d")
    scraping_cfg = config.get("scraping", {})
    sentiment_cfg = config.get("sentiment", {})

    # Per-user loop
    for user in users:
        name, topics = user["name"], user["topics"]
        to_email = ",".join(user["emails"])
        print(f"\n── User group: {name} ────────────────────────")
        if not to_email:
            print(f"  Warning: No recipients configured for '{name}' (check env var {group_name_to_env_key(name)}) — skipping")
            continue

        relevant = filter_relevant_articles(fresh, topics)
        print(f"  Found {len(relevant)} relevant articles")

        if scraping_cfg.get("enabled", True):
            print("Step 3a: Scraping full article content...")
            scraped_count = 0
            for article in relevant:
                if not article.get("scraped"):
                    scraped = scrape_article(
                        article["link"],
                        max_chars=scraping_cfg.get("max_chars", 2000),
                        timeout=scraping_cfg.get("timeout_seconds", 10),
                    )
                    if scraped:
                        article["summary"] = scraped
                    article["scraped"] = True
                    scraped_count += 1
            print(f"  Scraped {scraped_count} new articles")

        summarized = summarize_articles(relevant, topics)

        if sentiment_cfg.get("enabled", True):
            print("  Analyzing article sentiment...")
            summarized = analyze_sentiment(summarized)

        html = compile_digest(summarized, topics)
        try:
            send_email(
                html_content=html,
                subject=f"AI Research Digest ({name}) - {today}",
                from_email=os.getenv("GMAIL_FROM"),
                to_email=to_email,
                app_password=os.getenv("GMAIL_APP_PASSWORD"),
            )
            print(f"  Digest sent to {to_email} ({name})")
        except Exception as e:
            print(f"  Warning: Failed to send email to {to_email} ({name}): {e}")

    # Cache after all users processed
    add_to_cache([a["link"] for a in fresh])
    print(f"\n  Cached {len(fresh)} article URLs")
    print("Done!")


if __name__ == "__main__":
    main()
