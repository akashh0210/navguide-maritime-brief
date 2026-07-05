# NavGuide Weekly Maritime Intelligence Brief — Architecture & Build Plan

**Owner:** Akash
**Platform:** GitHub Actions (scheduler + manual trigger) + Python + Google Gemini + Gmail SMTP
**Goal:** A fully automated agent that emails a Weekly Maritime Intelligence Brief to captain@navguidesolutions.com every Monday 8:00 AM IST, with zero human involvement between Sunday night and Monday morning, and a manual trigger so the evaluator can run it on demand.

---

## 1. System Overview

```
                    ┌─────────────────────────────────────────┐
                    │         TRIGGER LAYER (GitHub)          │
                    │  • schedule: cron → Mon 08:00 IST       │
                    │  • workflow_dispatch → manual button    │
                    └───────────────────┬─────────────────────┘
                                        │
                                        ▼
   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
   │  1. FETCH    │──▶│  2. FILTER   │──▶│ 3. ENRICH    │──▶│  4. DELIVER  │
   │ news sources │   │ dedupe/rank  │   │ Gemini LLM   │   │  HTML email  │
   └──────────────┘   └──────────────┘   └──────────────┘   └──────────────┘
        │                   │                   │                   │
   fail: skip source   fail: flag <5      fail: retry x1      fail: raise,
   continue others     stories, say so    then fallback       visible in log
```

Every arrow is a natural seam. Each stage owns one responsibility, has its own failure path, and logs its outcome to stdout so the whole run is auditable from the GitHub Actions log.

---

## 2. Phase-Wise Build

### Phase 0 — Scaffold & Secrets (setup, ~15 min)
**Aim:** Empty repo that can run a Python job on a schedule.

- Create repo (e.g. `navguide-maritime-brief`).
- Add `requirements.txt`: `feedparser`, `google-genai`, `python-dateutil`, `beautifulsoup4` (for cleaning RSS HTML), `requests`.
- Add `.github/workflows/weekly-brief.yml` with both `schedule:` and `workflow_dispatch:`.
- Define 4 GitHub Secrets (never hardcoded):
  - `GEMINI_API_KEY`
  - `GMAIL_ADDRESS`
  - `GMAIL_APP_PASSWORD`
  - `RECIPIENT_EMAIL` (set to your own email during testing; switch to captain@navguidesolutions.com only for the final live run)
- **Exit check:** a stub `main.py` that prints "hello" runs green via the manual trigger.

### Phase 1 — Fetch (news sourcing)
**Aim:** Pull raw maritime news from the past 7 days with no API key dependency.

- Source: Google News RSS (`https://news.google.com/rss/search?q=...&hl=en-IN&gl=IN&ceid=IN:en`). No key, no rate-limit signup.
- Run 4-5 targeted queries, each as a separate feed:
  1. shipowners maritime shipping
  2. port operations port project
  3. marine casualty collision grounding vessel
  4. IMO regulation sanctions maritime
  5. vessel detention port state control
- Parse each with `feedparser`. Keep title, link, published date, source, snippet.
- Hard filter to the last 7 days by published date.
- **Failure handling:** wrap each feed fetch in try/except. On empty or error, log `WARN: source X skipped` and continue. One dead source must never kill the run.
- **Exit check:** prints a combined list of N articles with dates, all within 7 days.

### Phase 2 — Filter, Dedupe, Rank
**Aim:** Turn a messy pile of articles into a clean candidate set.

- Normalize titles (lowercase, strip punctuation) and dedupe by fuzzy title match so the same story from two outlets appears once.
- Rank by a simple relevance heuristic: recency + keyword hits (shipowner, port, inspection, detention, GT, IMO, sanctions).
- Keep top ~15 candidates to hand to the LLM (enough context, controlled token cost).
- **Failure handling:** if fewer than 5 usable candidates remain, set a flag `low_volume=True` so the brief can say so honestly instead of padding.
- **Exit check:** deduped, ranked candidate list printed with scores.

### Phase 3 — Enrich (Gemini)
**Aim:** Produce the three graded sections in the exact format the brief wants.

Single structured Gemini call (gemini-2.5-flash) that returns JSON with:
- `top_stories`: exactly up to 5 items, each `{title, two_line_summary, link}`.
- `major_incidents`: incidents involving vessels over 10,000 GT (collision, grounding, detention, sanctions). Empty list is valid.
- `opportunity_signal`: one `{headline, why_it_matters}` written for a founder/managing-partner audience, tied to NavGuide's consulting business.

Prompt rules baked in: only use provided articles, never invent links, if a section has no qualifying items say so, keep summaries to 2 lines.

- **Failure handling:**
  - Wrap the call, retry once on failure.
  - Validate the returned JSON parses and has the expected keys before use.
  - If it still fails or returns garbage, fall back to a plain headline+link list, clearly labelled `[FALLBACK — LLM step failed]` in the email so the evaluator sees honest degradation, not silence.
- **Exit check:** valid JSON object with the three sections.

### Phase 4 — Deliver (Email)
**Aim:** A clean HTML email in the inbox.

- Build an HTML body: header with date range, the three sections, footer noting it was generated automatically.
- Send via Gmail SMTP over SSL (port 465) using `GMAIL_ADDRESS` + `GMAIL_APP_PASSWORD`.
- Recipient from `RECIPIENT_EMAIL` env var (your email in testing, captain's for the real run).
- Subject: `Weekly Maritime Intelligence Brief — [date range]`.
- **Failure handling:** if SMTP fails, raise loudly so the GitHub Actions run shows red and you get notified, rather than a silent no-send.
- **Exit check:** a real email lands in your test inbox.

### Phase 5 — Schedule & Prove
**Aim:** Turn it from "runs when I press it" into "runs itself."

- Confirm cron `30 2 * * 1` (02:30 UTC = 08:00 IST, Monday). Note GitHub cron is UTC and can drift a few minutes; document this.
- Confirm `workflow_dispatch` button works from the Actions tab.
- Do one full real run to generate this week's actual brief (needed for the submission email).
- **Exit check:** green run in Actions history + real brief in inbox.

---

## 3. Failure-Handling Summary (grading-critical)

| Failure | Behaviour |
|---|---|
| A news source is down/empty | Log warning, skip it, continue with the rest |
| Fewer than 5 relevant stories | Brief states this explicitly, no filler |
| No qualifying >10,000 GT incident | Section says "no major incidents this week" |
| Gemini call fails / bad output | Retry once, then plain-headline fallback, labelled honestly |
| SMTP send fails | Raise error, run goes red, visible in Actions log |
| Cost overrun risk | Cap candidates (~15) + one LLM call per run, well under Rs 500 |

---

## 4. What Stays Manual (be honest in the build note)

The **opportunity signal's commercial judgment** stays human-verified. Gemini can surface a plausible new port project or regulation, but deciding whether it is genuinely worth NavGuide's business time needs someone who knows their client base and service lines. The agent proposes; a human still decides. This is a deliberate choice, not a gap.

---

## 5. Repo Structure

```
navguide-maritime-brief/
├── .github/workflows/weekly-brief.yml
├── src/
│   ├── main.py            # orchestrator
│   ├── news_sources.py    # Phase 1 fetch
│   ├── filter_rank.py     # Phase 2
│   ├── enrich.py          # Phase 3 Gemini
│   └── emailer.py         # Phase 4 SMTP
├── requirements.txt
├── ARCHITECTURE.md        # this file
└── README.md              # run + secrets instructions
```

---

## 6. Build Order Checklist

- [ ] Phase 0: repo + workflow stub + 4 secrets, stub run green
- [ ] Phase 1: fetch working, all within 7 days, dead source survives
- [ ] Phase 2: dedupe + rank + low-volume flag
- [ ] Phase 3: Gemini JSON output + retry + fallback validated
- [ ] Phase 4: HTML email lands in test inbox
- [ ] Phase 5: schedule confirmed + manual trigger confirmed + real brief generated
- [ ] Switch RECIPIENT_EMAIL to captain@navguidesolutions.com for the final proof run
- [ ] Draft submission email (subject line, demo link + view access, this week's brief, 500-word build note, the word Anchor on its own line)
