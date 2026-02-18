import os
import json
import time
import re
import smtplib
import feedparser
import yaml
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
from groq import Groq

load_dotenv()
client = Groq(api_key=os.getenv("GROQ_API_KEY"))


def load_config(path="config.yaml"):
    with open(path) as f:
        return yaml.safe_load(f)


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


def summarize_articles(articles):
    """Summarize each relevant article into 3 bullet points (batched)."""
    if not articles:
        return []

    batch_size = 5

    for i in range(0, len(articles), batch_size):
        batch = articles[i:i + batch_size]
        articles_text = ""
        for j, article in enumerate(batch, 1):
            articles_text += f"[{j}] Title: {article['title']}\nContent: {article['summary'][:400]}\n\n"

        prompt = f"""Summarize each article in exactly 3 concise bullet points.
Focus on practical insights for finance and technology professionals.

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
        for article in articles:
            score = article.get("relevance_score", 0)
            bar_color = "#28a745" if score >= 9 else "#4a90d9" if score >= 7 else "#fd7e14"
            bullets_html = article.get("bullets", "").replace("\n", "<br>").replace("•", "&#8226;")
            html += f"""  <div style="margin: 20px 0; padding: 18px; border-left: 4px solid {bar_color}; background: #f8f9fa; border-radius: 0 6px 6px 0;">
    <h3 style="margin: 0 0 6px 0; font-size: 16px; line-height: 1.4;">
      <a href="{article['link']}" style="color: #1a1a2e; text-decoration: none;">{article['title']}</a>
    </h3>
    <p style="color: #999; font-size: 12px; margin: 0 0 10px 0;">
      {article['source']} &nbsp;·&nbsp; {article['published']} &nbsp;·&nbsp; Relevance: {score}/10
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
    """Send HTML email via Gmail SMTP."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = to_email
    msg.attach(MIMEText(html_content, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(from_email, app_password)
        server.sendmail(from_email, to_email, msg.as_string())


def main():
    config = load_config()

    print("Step 1/4: Fetching articles from RSS feeds...")
    articles = fetch_articles(config["feeds"])
    print(f"  Found {len(articles)} total articles")

    print("Step 2/4: Filtering relevant articles with AI...")
    relevant = filter_relevant_articles(articles, config["topics"])
    print(f"  Found {len(relevant)} relevant articles")

    print("Step 3/4: Summarizing articles...")
    summarized = summarize_articles(relevant)

    print("Step 4/4: Sending digest email...")
    today = datetime.now().strftime("%Y-%m-%d")
    html = compile_digest(summarized, config["topics"])

    send_email(
        html_content=html,
        subject=f"AI Research Digest - {today}",
        from_email=os.getenv("GMAIL_FROM"),
        to_email=os.getenv("GMAIL_TO"),
        app_password=os.getenv("GMAIL_APP_PASSWORD"),
    )
    print(f"  Digest sent to {os.getenv('GMAIL_TO')}")
    print("Done!")


if __name__ == "__main__":
    main()
