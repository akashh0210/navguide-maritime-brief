# Weekly Maritime Intelligence Brief Agent

**Automatically emails a curated maritime intelligence brief every Monday at 08:00 IST - with zero human involvement.**

> Live and running on GitHub Actions. Trigger it yourself from the Actions tab above.

---

## What it does

Every week, this agent scans maritime news sources, filters and ranks the most relevant stories, passes them through Google Gemini for editorial summarisation, and delivers a clean HTML email brief to the configured recipient.

The brief contains three sections:

1. **Top Stories** - the five most significant maritime news items of the past seven days, each with a two-sentence plain-English summary and a link to the source.
2. **Major Incidents** - any collisions, groundings, detentions, or sanctions actions involving vessels over 10,000 GT. If there were none this week, the section says so honestly.
3. **Opportunity Signal** - one business-relevant development (a port project, regulation change, or market shift) with a short note on the consulting angle it opens for NavGuide Solutions.

The entire process runs automatically. No one presses a button on Monday morning; the schedule handles it. A manual trigger button is also available for on-demand runs.

---

## How to run it

### Option A: Trigger the live agent (no setup needed)

This is the recommended path for evaluators.

1. Click the **Actions** tab at the top of this repo page.
2. In the left sidebar, click **Weekly Maritime Intelligence Brief**.
3. Click the **Run workflow** button (top right of the run list).
4. Click the green **Run workflow** button in the dropdown.
5. Watch the run turn green - takes roughly 40-60 seconds.
6. The brief email arrives in the configured inbox immediately after the run completes.

All four secrets (API key, Gmail credentials, recipient address) are already configured in this repo's Settings. Nothing else is needed.

### Option B: Run locally (for developers)

**Prerequisites:** Python 3.12+

```bash
# 1. Clone the repo
git clone https://github.com/akashh0210/navguide-maritime-brief.git
cd navguide-maritime-brief

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create your local secrets file
cp .env.example .env
# Edit .env and fill in the four values (see Configuration section below)

# 4. Run the full pipeline
python src/main.py
```

To test individual stages without sending an email:

```bash
python src/news_sources.py   # Phase 1: prints fetched articles with dates
python src/filter_rank.py    # Phase 2: prints ranked candidates and incident list
python src/enrich.py         # Phase 3: prints the three brief sections as JSON
```

---

## How it works

The pipeline has four stages. Each stage has exactly one responsibility and its own failure path.

```
Fetch  -->  Filter/Rank  -->  Gemini Enrich  -->  Email
```

**Stage 1 - Fetch** (`src/news_sources.py`)
Pulls from 11 Google News RSS queries (no API key required) plus a direct gCaptain incidents feed. Hard-filters to articles published in the last seven days. Each source is wrapped in try/except - a dead feed is logged as a warning and skipped; the rest continue.

**Stage 2 - Filter and Rank** (`src/filter_rank.py`)
Removes market-research press releases (auto-detected by title pattern). Deduplicates near-identical stories using Jaccard similarity on normalised title tokens. Applies a topic-cluster diversity cap so one story from five outlets does not dominate the list. Scores remaining articles on recency and maritime keyword density. Outputs the top 15 candidates plus a labelled subset of incident-type articles for Stage 3.

**Stage 3 - Gemini Enrichment** (`src/enrich.py`)
Sends the candidates to `gemini-2.5-flash` with a structured Pydantic schema as the response format, so the model is forced to return valid JSON. Thinking is disabled (`thinking_budget=0`) to prevent token budget truncation. The prompt instructs the model to use only provided articles, copy links verbatim, apply the over-10,000-GT vessel size filter, and exclude near-miss/avoidance events from the incidents section. Retries once on failure; falls back to a plain headline list if both attempts fail.

**Stage 4 - Email** (`src/emailer.py`)
Builds a clean HTML email (table layout, inline styles, mobile-readable) with a plain-text alternative for clients that do not render HTML. Sends via Gmail SMTP over SSL on port 465. Subject line includes the date range covered.

Full architectural detail is in [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Failure handling

Reliability under partial failure is an explicit design goal. Here is what the code actually does in each failure scenario:

| Failure | Behaviour |
|---|---|
| A news source is down or returns an empty feed | Logged as `WARN: source ... skipped`. All other sources continue. The pipeline never stops for one bad feed. |
| Fewer than 5 relevant stories found after filtering | `low_volume=True` flag is set. The brief states this honestly rather than padding with off-topic content. |
| No qualifying incidents over 10,000 GT this week | The Major Incidents section says "No major incidents involving vessels over 10,000 GT were reported this week." Never left blank. |
| Gemini returns truncated or unparseable JSON | The response is retried once. If that also fails, the email is sent with a plain headline and link list, labelled `[FALLBACK - automated summaries unavailable this run]` at the top. The degraded state is visible, not hidden. |
| SMTP send fails | A `RuntimeError` is raised immediately. The GitHub Actions run shows red and a notification is sent. No silent non-send. |

---

## Configuration

The pipeline reads four values from environment variables. In production these are GitHub Actions Secrets. For local testing, copy `.env.example` to `.env` and fill them in.

| Variable | What it is | Where to get it |
|---|---|---|
| `GEMINI_API_KEY` | Google AI API key for Gemini | [Google AI Studio](https://aistudio.google.com) - free tier is sufficient |
| `GMAIL_ADDRESS` | The Gmail account used to send the brief | Your Gmail address |
| `GMAIL_APP_PASSWORD` | A 16-character Gmail App Password | Google Account > Security > 2-Step Verification must be on, then App Passwords |
| `RECIPIENT_EMAIL` | Where the brief is delivered | Any email address |

**Security:** All four values are stored as GitHub Actions Secrets and are masked as `***` in every log line. The `.env` file for local use is listed in `.gitignore` and is never committed to the repository.

To add or update secrets in the repo: **Settings > Secrets and variables > Actions > New repository secret**.

---

## Schedule

| Trigger | When |
|---|---|
| Automatic schedule | Every Monday at 02:30 UTC (08:00 IST) |
| Manual trigger | Actions tab > Run workflow button, available any time |

The cron expression in `.github/workflows/weekly-brief.yml` is `30 2 * * 1`. GitHub Actions runs on UTC. Cron jobs can start a few minutes late under platform load; this is expected and does not affect the brief's content.

---

## Repo structure

```
navguide-maritime-brief/
|
|- .github/workflows/
|   `- weekly-brief.yml      # GitHub Actions: schedule + manual trigger, injects secrets
|
|- src/
|   |- main.py               # Pipeline orchestrator: runs Phases 1-4 in order
|   |- news_sources.py       # Phase 1: Google News RSS fetch + gCaptain direct feed
|   |- filter_rank.py        # Phase 2: spam filter, dedupe, cluster cap, relevance scoring
|   |- enrich.py             # Phase 3: Gemini structured call, retry, fallback
|   `- emailer.py            # Phase 4: HTML/plain-text build, Gmail SMTP send
|
|- ARCHITECTURE.md           # Full design document: phases, failure paths, decisions
|- requirements.txt          # Python dependencies
|- .env.example              # Template for local secrets (copy to .env, never commit)
`- README.md                 # This file
```

---

## Tech stack

| Component | Technology |
|---|---|
| Scheduler and runner | GitHub Actions (ubuntu-latest, Python 3.12) |
| News sources | Google News RSS (11 queries, no API key) + gCaptain incidents RSS |
| Summarisation | Google Gemini 2.5-flash via google-genai SDK |
| Email delivery | Gmail SMTP over SSL (port 465) |
| Language | Python 3.12 |
| Key libraries | feedparser, google-genai, beautifulsoup4, pydantic, python-dotenv |

**What is intentionally left to a human:** The Opportunity Signal section surfaces a plausible consulting angle from the week's news, but whether that signal is worth NavGuide's time requires someone who knows the firm's clients and current pipeline. The agent proposes; a human decides. This is a deliberate design choice, not a gap.

**What would come next:** A feedback loop where the recipient can rate the brief quality, adaptive query tuning based on open/click data, and a Slack or WhatsApp delivery option alongside email.
