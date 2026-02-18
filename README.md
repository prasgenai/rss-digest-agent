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
├── test_main.py      # Unit tests (27 tests)
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

# ── Digest Recipient(s) ────────────────────────────────────
# The email address(es) the digest will be delivered TO
# Can be the same as GMAIL_FROM or different addresses
# Supports multiple recipients separated by comma or semicolon
GMAIL_TO=your_email@gmail.com
# GMAIL_TO=person1@gmail.com,person2@gmail.com
# GMAIL_TO=person1@gmail.com;person2@gmail.com;person3@gmail.com

# ── Gmail App Password ─────────────────────────────────────
# NOT your Gmail login password — a separate 16-char app password
# How to generate: myaccount.google.com → Security → App Passwords
# Enter without spaces (e.g. abcdabcdabcdabcd)
GMAIL_APP_PASSWORD=your16charapppassword
```

> **Never commit `.env` to git.** It is already excluded via `.gitignore`.

### 4. Customize topics and feeds

Edit `config.yaml` to add/remove RSS feeds or change the topics the AI filters for.

---

## Running

```bash
python3 main.py
```

Expected output:
```
Step 1/4: Fetching articles from RSS feeds...
  Found 30 total articles
Step 2/4: Filtering relevant articles with AI...
  Found 7 relevant articles
Step 3/4: Summarizing articles...
Step 4/4: Sending digest email...
  Digest sent to your_email@gmail.com
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

## Security Notes

- Never commit `.env` to git (already excluded via `.gitignore`)
- Rotate your Groq API key and Gmail App Password periodically
- The Gmail App Password grants access only to Gmail — not your Google account password
