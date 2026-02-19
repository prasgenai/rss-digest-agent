# RSS Research Digest Agent

An agentic app that fetches articles from RSS feeds, filters them by topic using AI, summarizes them into bullet points, and emails you a daily digest.

**Powered by:** Groq (Llama 3.3) · feedparser · Gmail SMTP
**Cost:** ~$0/month (Groq free tier)

---

## What It Does

1. Fetches articles from configured RSS feeds (last 24 hours)
2. Uses an LLM to score and filter articles relevant to your topics
3. Summarizes each relevant article into 3 bullet points
4. Sends a formatted HTML digest to your email

**Default topics:**
- AI use cases for Finance / Banking (fraud detection, risk, compliance, forecasting)
- AI and Claude for software development (coding agents, code review, LLM tooling)

---

## Project Structure

```
rss-digest-agent/
├── .env              # API keys and email credentials (never commit this)
├── .gitignore        # Excludes .env from git
├── .dockerignore     # Excludes .env and dev files from Docker image
├── config.yaml       # RSS feeds and topics (edit this to customize)
├── Dockerfile        # Docker container definition
├── requirements.txt  # Python dependencies
├── main.py           # Main agent logic
├── test_main.py      # Unit tests (72 tests)
└── README.md
```

---

## Setup

### 1. Prerequisites

- Python 3.10+
- A [Groq API key](https://console.groq.com) (free)
- A Gmail account with an [App Password](https://myaccount.google.com/apppasswords)

### 2. Install dependencies

```bash
pip3 install -r requirements.txt
```

### 3. Configure credentials

Create a `.env` file in the project root by copying the sample below:

```env
# ── Groq API ──────────────────────────────────────────────
# Get your free key at https://console.groq.com → API Keys
GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# ── Gmail Sender ───────────────────────────────────────────
# The Gmail address the digest will be sent FROM
GMAIL_FROM=your_email@gmail.com

# ── Digest Recipient(s) — single-user mode ──────────────────
# Used only when 'users:' is absent from config.yaml
# Supports multiple recipients separated by comma or semicolon
GMAIL_TO=your_email@gmail.com
# GMAIL_TO=person1@gmail.com,person2@gmail.com
# GMAIL_TO=person1@gmail.com;person2@gmail.com;person3@gmail.com

# ── Per-group recipient emails — multi-user mode ─────────────
# One env var per user group defined in config.yaml.
# Name is derived from the group name: uppercase, spaces/hyphens
# replaced with underscores, _EMAILS appended.
# FINANCE_TEAM_EMAILS=person1@gmail.com,person2@gmail.com
# TECHNOLOGY_TEAM_EMAILS=tech@gmail.com
# A_LEVEL_STUDENTS_EMAILS=student@gmail.com

# ── Gmail App Password ─────────────────────────────────────
# NOT your Gmail login password — a separate 16-char app password
# How to generate: myaccount.google.com → Security → App Passwords
# Enter without spaces (e.g. abcdabcdabcdabcd)
GMAIL_APP_PASSWORD=your16charapppassword
```

> **Never commit `.env` to git.** It is already excluded via `.gitignore`.

### 4. Customize topics and feeds

Edit `config.yaml` to add/remove RSS feeds or change the topics the AI filters for.

### 5. Configure user groups (optional)

The agent supports multiple user groups, each with their own topics and email recipients. RSS feeds are fetched **once** and shared; filtering, summarization, and email delivery happen independently per group.

Add a `users:` block in `config.yaml` (topics only — no emails):

```yaml
users:
  - name: Finance Team
    topics:
      - AI use cases for Finance Department in a bank
      - Regulatory technology and compliance automation

  - name: Technology Team
    topics:
      - AI and Claude for software development
      - Open source AI models and LLM infrastructure
```

Then add the corresponding email env vars to `.env`. The env var name is derived from the group name — uppercase, spaces/hyphens replaced with underscores, `_EMAILS` appended:

```env
FINANCE_TEAM_EMAILS=person1@gmail.com,person2@gmail.com
TECHNOLOGY_TEAM_EMAILS=tech@gmail.com
```

- When `users:` is present, `GMAIL_TO` is ignored — recipients come from per-group env vars in `.env`
- When `users:` is absent, the agent falls back to single-user mode using `GMAIL_TO` and `topics:` from `config.yaml`
- Each group receives a digest with its own subject line: `AI Research Digest (Finance Team) - 2026-02-18`
- Keeping emails in `.env` (not `config.yaml`) ensures recipient addresses are never committed to version control

---

## Running

```bash
python3 main.py
```

Expected output (multi-user mode):
```
Step 1: Fetching articles from RSS feeds...
  Found 30 unique articles
  28 new (skipped 2 already seen)

── User group: Finance Team ────────────────────────
  Found 5 relevant articles
  Digest sent to finance_recipient1@example.com,finance_recipient2@example.com (Finance Team)

── User group: Technology Team ────────────────────────
  Found 4 relevant articles
  Digest sent to finance_recipient1@example.com,finance_recipient2@example.com (Technology Team)

  Cached 28 article URLs
Done!
```

---

## Schedule Daily Digest (Linux/macOS)

Run `crontab -e` and add:

```
0 8 * * * cd /home/prashant/claude_practice/rss-digest-agent && python3 main.py >> /tmp/digest.log 2>&1
```

This runs the agent every day at 8:00 AM and logs output to `/tmp/digest.log`.

---

## Adding More RSS Feeds

Edit `config.yaml` and add feed URLs under `feeds:`:

```yaml
feeds:
  - https://example.com/feed.xml
```

To find the RSS feed URL for any website, look for an RSS icon or append `/feed` or `/rss` to the site URL.

---

## Sentiment Analysis

When enabled, each article in the digest is classified as **Positive**, **Negative**, or **Neutral** based on its implications for finance and technology professionals. The sentiment label appears colour-coded in the email next to the relevance score.

Configure in `config.yaml`:

```yaml
sentiment:
  enabled: true   # set to false to skip sentiment analysis
```

- Runs after summarization — uses bullet points for more accurate classification
- Invalid or unrecognised LLM responses default to Neutral
- If the Groq API call fails, all articles in the affected batch are set to Neutral
- Set `enabled: false` for faster runs when sentiment is not needed

---

## Running with Docker

Docker lets you run the agent in an isolated container without installing Python or dependencies locally.

### 1. Prerequisites

- [Docker](https://docs.docker.com/get-docker/) installed and running
- `.env` file configured with your credentials (see Setup above)

### 2. Build the image

```bash
docker build -t rss-digest-agent .
```

### 3. Run the container

Pass your `.env` file securely at runtime — it is never baked into the image:

```bash
docker run --env-file .env rss-digest-agent
```

### 4. Schedule with cron (Docker)

```
0 8 * * * docker run --env-file /home/prashant/claude_practice/rss-digest-agent/.env rss-digest-agent >> /tmp/digest.log 2>&1
```

> **Note:** The `.env` file is excluded from the Docker image via `.dockerignore`. Always pass it with `--env-file` at runtime.

---

## Full Article Scraping

When enabled, the agent fetches the full article text from each relevant article's URL instead of relying on the truncated RSS excerpt. This produces richer, more accurate summaries.

Configure in `config.yaml`:

```yaml
scraping:
  enabled: true          # set to false to use RSS excerpts only (faster runs)
  max_chars: 2000        # maximum characters used from scraped content
  timeout_seconds: 10    # page load timeout in seconds
```

- Scraping runs **after** AI filtering — only relevant articles are scraped
- If a site blocks scraping or times out, the agent silently falls back to the RSS excerpt
- Set `enabled: false` for faster runs or if you hit many paywalled sources

---

## Article Cache

The agent maintains a local SQLite cache (`digest_cache.db`) to avoid re-processing articles it has already seen.

- Created automatically on first run — no setup needed
- Stores article URLs with the date they were first processed
- Expiry period configurable in `config.yaml` under `cache.expiry_days` (default: 7 days)
- Expired entries are purged automatically on each run
- Excluded from git via `.gitignore` — stays local only

To reset the cache and reprocess all articles:
```bash
rm digest_cache.db
```

---

## Security Notes

- Never commit `.env` to git (already excluded via `.gitignore`)
- Recipient email addresses (per-group `*_EMAILS` vars) live in `.env`, not `config.yaml`, so they are never committed to version control
- Rotate your Groq API key and Gmail App Password periodically
- The Gmail App Password grants access only to Gmail — not your Google account password
