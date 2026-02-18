# Software Design Document
## RSS Research Digest Agent

| Field         | Details                          |
|---------------|----------------------------------|
| Document Ver  | 1.0                              |
| Date          | February 2026                    |
| Author        | Prashant                         |
| Status        | Released                         |

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Business Context & Problem Statement](#2-business-context--problem-statement)
3. [Business Flow](#3-business-flow)
4. [System Architecture](#4-system-architecture)
5. [Technical Flow](#5-technical-flow)
6. [Tech Stack](#6-tech-stack)
7. [Component Design](#7-component-design)
8. [Data Design](#8-data-design)
9. [Security Design](#9-security-design)
10. [Deployment & Operations](#10-deployment--operations)
11. [Limitations & Future Enhancements](#11-limitations--future-enhancements)

---

## 1. Executive Summary

### Overview

The **RSS Research Digest Agent** is a lightweight, AI-powered application that automatically monitors multiple RSS feeds, filters articles relevant to specified topics using a Large Language Model (LLM), summarizes the content into concise bullet points, and delivers a formatted daily email digest to the user.

### Purpose

Knowledge workers — particularly professionals in Finance and Technology — are overwhelmed by the volume of industry news published daily. Manually browsing multiple websites and reading full articles to find relevant insights is time-consuming and inefficient.

This application solves that problem by acting as an **intelligent research assistant** that works autonomously every day, delivering only what matters to the user's inbox.

### Key Outcomes

| Outcome | Description |
|---|---|
| Time Saved | Eliminates daily manual browsing of multiple news sources |
| Signal vs Noise | AI filters out irrelevant content automatically |
| Actionable Insights | Each article is summarized into 3 practical bullet points |
| Zero Maintenance | Runs on a scheduler; requires no daily user interaction |
| Near-Zero Cost | Operates within the free tier of the Groq API |

### Target Users

- Finance professionals in banking (risk, compliance, reporting teams)
- Technology teams using AI tools for software development
- Any knowledge worker who wants a curated daily news digest

---

## 2. Business Context & Problem Statement

### Problem

| Pain Point | Impact |
|---|---|
| Too many news sources to monitor | Hours lost per week scanning irrelevant content |
| No intelligent filtering | Users must read full articles to assess relevance |
| No summarization | High cognitive load to extract key insights |
| Inconsistent reading habits | Important developments missed on busy days |

### Solution

An automated agent that:
1. Monitors RSS feeds from trusted industry sources
2. Uses AI to understand topic relevance — not just keyword matching
3. Summarizes articles into digestible bullet points
4. Delivers everything to your inbox on a fixed schedule

### Business Value

```
Manual Process (daily):       Automated Process (daily):
─────────────────────         ──────────────────────────
Open 10+ websites             Cron triggers agent at 8 AM
Read 30+ article headlines    Agent fetches 30 articles
Read 10+ full articles        LLM filters to 7 relevant
Take personal notes           LLM summarizes each article
~45 minutes                   Email delivered in ~2 minutes
                              User reads digest: ~5 minutes
```

---

## 3. Business Flow

### Daily Workflow

```
┌─────────────────────────────────────────────────────────────────┐
│                        DAILY TRIGGER (8 AM)                     │
│                         Cron Scheduler                          │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                      CONTENT COLLECTION                         │
│   Fetch latest articles from 11 RSS feeds                       │
│   Sources: Finextra, Finovate, GitHub Blog, HN, VentureBeat...  │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                      AI FILTERING AGENT                         │
│   LLM reads each article title + summary                        │
│   Scores relevance 1–10 against configured topics               │
│   Articles scoring ≥ 7 pass through                             │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                     AI SUMMARIZATION AGENT                      │
│   LLM reads each relevant article                               │
│   Generates 3 concise, insight-driven bullet points             │
│   Focus: practical implications for finance & tech teams        │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                       DIGEST COMPILATION                        │
│   Articles assembled into formatted HTML email                  │
│   Color-coded by relevance score                                │
│   Each article: title, source, date, score, bullet points       │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                         EMAIL DELIVERY                          │
│   HTML digest sent via Gmail SMTP                               │
│   Delivered to: finance_recipient1@example.com                             │
│   User reads digest at their convenience                        │
└─────────────────────────────────────────────────────────────────┘
```

### User Journey

```
User sets up agent once
        │
        ▼
User configures topics in config.yaml
        │
        ▼
User schedules via cron
        │
        ▼
Every morning: digest arrives in inbox
        │
        ▼
User reads 5-minute summary of the day's relevant AI news
        │
        ▼
User clicks links to read full articles of interest
```

---

## 4. System Architecture

### Architecture Style

**Pipeline Architecture** — a linear sequence of independent processing stages where the output of each stage feeds into the next. This pattern is ideal for ETL-style workflows like this one.

### High-Level Architecture Diagram

```
 EXTERNAL SOURCES          APPLICATION CORE              OUTPUT
 ───────────────    ───────────────────────────────    ─────────
                   │                               │
 RSS Feed 1 ──────►│  ┌─────────┐   ┌──────────┐  │
 RSS Feed 2 ──────►│  │ Fetcher │──►│  Filter  │  │
 RSS Feed 3 ──────►│  └─────────┘   │  Agent   │  │
    ...            │                └────┬─────┘  │
 RSS Feed 11 ─────►│                     │        │
                   │              ┌──────▼──────┐ │
 Groq API ◄────────┼──────────────│ Summarizer  │ │
 (Llama 3.3) ──────┼─────────────►│   Agent    │ │
                   │              └──────┬──────┘ │
                   │                     │        │
                   │              ┌──────▼──────┐ │
                   │              │  Compiler   │ │──► Gmail SMTP ──► Inbox
                   │              └─────────────┘ │
                   │                               │
                   └───────────────────────────────┘

 CONFIG LAYER
 ─────────────
 config.yaml  ──► topics, feed URLs
 .env         ──► API keys, email credentials
```

### Component Interaction

```
main.py
  │
  ├── load_config()          reads config.yaml
  │
  ├── fetch_articles()       calls feedparser → RSS URLs
  │
  ├── filter_relevant()      calls Groq API (batched, 5 articles/call)
  │
  ├── summarize_articles()   calls Groq API (batched, 5 articles/call)
  │
  ├── compile_digest()       pure Python HTML builder
  │
  └── send_email()           calls smtplib → Gmail SMTP
```

### Design Principles Applied

| Principle | How Applied |
|---|---|
| Single Responsibility | Each function does exactly one thing |
| Separation of Concerns | Config, logic, and output are cleanly separated |
| Fail Gracefully | Each stage has try/except; failures produce warnings, not crashes |
| Stateless | No database; the app runs, delivers, and exits |
| Cost Efficiency | Batching minimizes API calls; free-tier compatible |

---

## 5. Technical Flow

### Step-by-Step Technical Execution

#### Step 1 — Initialization
```
python3 main.py
    │
    ├── load_dotenv()          loads .env into os.environ
    ├── Groq(api_key=...)      initializes Groq client
    └── load_config()          parses config.yaml → dict
```

#### Step 2 — Article Fetching
```
fetch_articles(feeds, hours=24)
    │
    ├── For each feed_url in config['feeds']:
    │       feedparser.parse(feed_url)     # HTTP GET to RSS endpoint
    │       for each entry in feed.entries:
    │           parse published_parsed     # datetime from RSS timestamp
    │           filter: published >= now - 24h
    │           append: {title, link, summary, published, source}
    │
    └── Returns: List[Dict]  (~30 articles)
```

#### Step 3 — AI Filtering (Agentic Step 1)
```
filter_relevant_articles(articles, topics)
    │
    ├── Split articles into batches of 5
    │
    ├── For each batch:
    │       Build prompt:
    │           - topics list
    │           - article titles + summaries (200 chars each)
    │           - instruction: return JSON array with scores
    │
    │       Groq API call:
    │           model: llama-3.3-70b-versatile
    │           temperature: 0  (deterministic scoring)
    │           max_tokens: 300
    │
    │       Parse JSON response:
    │           regex extract [...] from response
    │           json.loads()
    │           keep articles where score >= 7
    │
    │       time.sleep(1)   # rate limit control
    │
    ├── Sort by relevance_score descending
    └── Return: top 12 articles max
```

#### Step 4 — AI Summarization (Agentic Step 2)
```
summarize_articles(articles)
    │
    ├── Split articles into batches of 5
    │
    ├── For each batch:
    │       Build prompt:
    │           - article titles + content (400 chars each)
    │           - instruction: 3 bullet points each, [N] format
    │
    │       Groq API call:
    │           model: llama-3.3-70b-versatile
    │           temperature: 0.3  (slight creativity for summaries)
    │           max_tokens: 1500
    │
    │       Parse response:
    │           re.split(r'\[(\d+)\]', text)
    │           map section index → article
    │           store bullets in article dict
    │
    │       time.sleep(1)
    │
    └── Returns: articles with 'bullets' field populated
```

#### Step 5 — Digest Compilation
```
compile_digest(articles, topics)
    │
    ├── Build HTML string with inline CSS
    ├── Header: dark blue banner, date, article count
    ├── For each article:
    │       color = green if score>=9, blue if >=7, orange otherwise
    │       render: title (linked), source, date, score, bullets
    └── Returns: HTML string
```

#### Step 6 — Email Delivery
```
send_email(html, subject, from, to, app_password)
    │
    ├── MIMEMultipart('alternative')    # email container
    ├── MIMEText(html, 'html')          # HTML content
    ├── smtplib.SMTP_SSL('smtp.gmail.com', 465)
    │       server.login(from, app_password)
    │       server.sendmail(from, to, msg.as_string())
    └── Connection auto-closed (context manager)
```

### Groq API Call Summary

| Stage | Calls | Model | Temp | Max Tokens |
|---|---|---|---|---|
| Filter | ceil(articles/5) | llama-3.3-70b-versatile | 0 | 300 |
| Summarize | ceil(relevant/5) | llama-3.3-70b-versatile | 0.3 | 1500 |
| **Typical total** | **~8 calls/run** | — | — | — |

---

## 6. Tech Stack

### Full Stack Overview

```
┌────────────────────────────────────────────────────┐
│                   APPLICATION LAYER                │
│   Language:  Python 3.10+                          │
│   Entry:     main.py (single-file architecture)    │
└────────────────────────────────────────────────────┘
┌────────────────────────────────────────────────────┐
│                   AI / LLM LAYER                   │
│   Provider:  Groq Cloud (free tier)                │
│   Model:     Meta Llama 3.3 70B Versatile          │
│   SDK:       groq 0.13.0                           │
│   Use:       Relevance filtering + Summarization   │
└────────────────────────────────────────────────────┘
┌────────────────────────────────────────────────────┐
│                  DATA COLLECTION LAYER             │
│   Library:   feedparser 6.0.11                     │
│   Protocol:  RSS 2.0 / Atom                        │
│   Transport: HTTP/HTTPS (handled by feedparser)    │
└────────────────────────────────────────────────────┘
┌────────────────────────────────────────────────────┐
│                   DELIVERY LAYER                   │
│   Protocol:  SMTP over SSL (port 465)              │
│   Library:   smtplib (Python stdlib)               │
│   Provider:  Gmail                                 │
│   Auth:      Gmail App Password                    │
└────────────────────────────────────────────────────┘
┌────────────────────────────────────────────────────┐
│                 CONFIGURATION LAYER                │
│   Secrets:   python-dotenv 1.0.1 + .env file       │
│   Config:    pyyaml 6.0.2 + config.yaml            │
└────────────────────────────────────────────────────┘
┌────────────────────────────────────────────────────┐
│                  SCHEDULING LAYER                  │
│   Tool:      Linux cron (crontab)                  │
│   Schedule:  Daily at 8:00 AM                      │
└────────────────────────────────────────────────────┘
```

### Dependencies

| Package | Version | License | Purpose |
|---|---|---|---|
| feedparser | 6.0.11 | MIT | Parse RSS/Atom feeds |
| groq | 0.13.0 | Apache 2.0 | Groq LLM API client |
| python-dotenv | 1.0.1 | BSD-3 | Load .env credentials |
| pyyaml | 6.0.2 | MIT | Parse config.yaml |
| smtplib | stdlib | PSF | Send email via SMTP |
| re | stdlib | PSF | Parse LLM responses |
| json | stdlib | PSF | Parse LLM JSON output |

All dependencies are **open source**. No proprietary libraries.

### RSS Feed Sources

| Feed | Category | URL |
|---|---|---|
| Finextra | Finance/Banking | finextra.com/rss |
| Finovate | Fintech | finovate.com/feed |
| FinTech Futures | Finance | fintechfutures.com/feed |
| Banking Technology | Banking | bankingtech.com/feed |
| WSJ Markets | Finance | feeds.a.dj.com |
| Anthropic Blog | AI/Claude | anthropic.com/rss.xml |
| GitHub Blog | Dev Tools | github.blog/feed |
| Hacker News | Tech | news.ycombinator.com/rss |
| DeepLearning.AI | AI Research | deeplearning.ai/the-batch/feed |
| VentureBeat AI | AI News | venturebeat.com/category/ai/feed |
| The New Stack | Dev/Cloud | thenewstack.io/feed |

### Cost Analysis

| Resource | Free Tier Limit | Daily Usage | Monthly Cost |
|---|---|---|---|
| Groq API | 14,400 req/day | ~8 requests | $0.00 |
| Gmail SMTP | 500 emails/day | 1 email | $0.00 |
| Compute | Local cron job | ~2 min/day | $0.00 |
| **Total** | | | **$0.00** |

---

## 7. Component Design

### `load_config(path)`
- **Input:** Path to YAML file (default: `config.yaml`)
- **Output:** Dict with `feeds` (list of URLs) and `topics` (list of strings)
- **Error handling:** Raises exception if file not found

### `fetch_articles(feeds, hours=24)`
- **Input:** List of RSS feed URLs, lookback window in hours
- **Output:** List of article dicts
- **Error handling:** Per-feed try/except — one failing feed does not stop others
- **Article schema:** `{title, link, summary, published, source}`

### `filter_relevant_articles(articles, topics)`
- **Input:** List of article dicts, list of topic strings
- **Output:** Filtered and scored list (max 12), sorted by relevance desc
- **Batching:** 5 articles per LLM call
- **Threshold:** Score ≥ 7 to pass
- **Rate limit:** 1 second sleep between batches

### `summarize_articles(articles)`
- **Input:** List of relevant article dicts
- **Output:** Same list with `bullets` field added to each dict
- **Batching:** 5 articles per LLM call
- **Fallback:** Uses raw RSS summary if LLM call fails

### `compile_digest(articles, topics)`
- **Input:** Summarized article list, topics list
- **Output:** HTML string (complete email body)
- **Color coding:** Green (9–10), Blue (7–8), Orange (< 7)

### `send_email(html, subject, from_email, to_email, app_password)`
- **Input:** HTML body, subject, credentials
- **Output:** None (side effect: email sent)
- **Protocol:** SMTP_SSL on port 465

---

## 8. Data Design

### Article Object (in-memory only, no persistence)

```python
{
    "title": str,            # Article headline
    "link": str,             # Full URL to article
    "summary": str,          # RSS-provided excerpt (max 500 chars)
    "published": str,        # Date string: "YYYY-MM-DD" or "Unknown"
    "source": str,           # Feed/publication name
    "relevance_score": int,  # Added by filter step: 1–10
    "bullets": str           # Added by summarize step: 3 bullet points
}
```

### Config Schema (`config.yaml`)

```yaml
topics:
  - string    # Natural language topic description

feeds:
  - string    # Valid RSS/Atom feed URL
```

### Environment Variables (`.env`)

```
GROQ_API_KEY          # Groq cloud API key
GMAIL_FROM            # Sender Gmail address
GMAIL_TO              # Recipient email address
GMAIL_APP_PASSWORD    # 16-character Gmail App Password (no spaces)
```

---

## 9. Security Design

### Credential Management

| Credential | Storage | Access |
|---|---|---|
| Groq API Key | `.env` file (local only) | Loaded at runtime via `python-dotenv` |
| Gmail App Password | `.env` file (local only) | Used once per run for SMTP auth |
| Gmail address | `.env` file | Not hardcoded in source |

### Security Controls

- `.env` is excluded from version control via `.gitignore`
- Gmail App Password grants Mail-only access — not full Google account access
- No credentials are logged or printed to console
- SMTP connection uses SSL (`SMTP_SSL`) — credentials transmitted encrypted
- Groq API calls use HTTPS

### Risks & Mitigations

| Risk | Mitigation |
|---|---|
| `.env` committed to git | `.gitignore` excludes it |
| Credentials shared in chat | Rotate Groq key and Gmail App Password after setup |
| LLM prompt injection via RSS content | Articles are only summarized, not executed |
| RSS feed serving malicious content | feedparser does not execute content; plain text only |

---

## 10. Deployment & Operations

### Running Manually

```bash
cd ~/claude_practice/rss-digest-agent
python3 main.py
```

### Scheduling with Cron

```bash
crontab -e
```

```
# Run daily at 8:00 AM, log output
0 8 * * * cd /home/prashant/claude_practice/rss-digest-agent && python3 main.py >> /tmp/digest.log 2>&1
```

### Checking Logs

```bash
cat /tmp/digest.log
```

### Customizing Topics or Feeds

Edit `config.yaml` — no code changes needed. The agent picks up changes on the next run.

### Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| `No relevant articles found` | Feeds had no recent articles | Check feed URLs are active |
| SMTP auth error | App Password incorrect | Regenerate Gmail App Password |
| Groq API error | Key invalid or rate limit hit | Check key in `.env`; wait 1 min |
| Email not received | Check spam folder | Add sender to Gmail contacts |

---

## 11. Limitations & Future Enhancements

### Current Limitations

| Limitation | Description |
|---|---|
| No deduplication | Same article appearing in multiple feeds will be processed twice |
| No article memory | Previously seen articles are re-fetched if still within 24 hours |
| Plain text fallback only | If Groq is down, email is not sent |
| No web scraping | Only RSS-provided summaries are used, not full article content |

### Potential Future Enhancements

| Enhancement | Benefit |
|---|---|
| SQLite article cache | Avoid re-processing seen articles |
| Full article scraping | Richer summaries beyond RSS excerpt |
| Multi-user support | Each user gets a personalized digest |
| Web UI for config | Non-technical users can manage feeds and topics |
| Slack/Teams delivery | Alternative to email |
| Weekly digest mode | Longer lookback window option |
| Sentiment analysis | Flag positive vs negative news per topic |

---

*Document generated for RSS Research Digest Agent v1.0*
*All technologies used are open source.*
