# NavGuide Weekly Maritime Intelligence Brief

Automated agent that emails a Weekly Maritime Intelligence Brief every Monday at 08:00 IST.

Built with: GitHub Actions + Python + Google Gemini (gemini-2.5-flash) + Gmail SMTP.

---

## 1. Add the 4 Required Secrets

Go to your repo on GitHub, then:
**Settings > Secrets and variables > Actions > New repository secret**

Add each of the following:

| Secret name | Value |
|---|---|
| `GEMINI_API_KEY` | Your Google AI Studio API key |
| `GMAIL_ADDRESS` | The Gmail address used to send (e.g. yourname@gmail.com) |
| `GMAIL_APP_PASSWORD` | A Gmail App Password (not your normal login password - generate one at myaccount.google.com/apppasswords) |
| `RECIPIENT_EMAIL` | Where to deliver the brief (your own email during testing; switch to captain@navguidesolutions.com for the final live run) |

> **Never commit secrets to the repo.** The workflow reads them only from GitHub Secrets at runtime.

---

## 2. Trigger a Manual Run

1. Go to the **Actions** tab in your GitHub repo.
2. Select **Weekly Maritime Intelligence Brief** from the left sidebar.
3. Click **Run workflow** (top-right of the workflow list), then **Run workflow** in the dropdown.
4. Watch the run in real time - logs stream in the Actions UI.

The scheduled run fires automatically every Monday at 02:30 UTC (08:00 IST). Note: GitHub Actions cron can drift a few minutes.

---

## 3. Run Locally for Testing

### Prerequisites

```bash
pip install -r requirements.txt
```

### Test Phase 1 - fetch (no secrets required)

```bash
python src/news_sources.py
```

Prints all articles fetched from Google News RSS for the 5 maritime queries, sorted newest-first. Every article should show a date within the last 7 days. Use this to confirm live fetching works before running the full pipeline.

### Run the full pipeline locally

Set the 4 secrets as environment variables first (Windows PowerShell):

```powershell
$env:GEMINI_API_KEY      = "your-key-here"
$env:GMAIL_ADDRESS       = "you@gmail.com"
$env:GMAIL_APP_PASSWORD  = "xxxx xxxx xxxx xxxx"
$env:RECIPIENT_EMAIL     = "your-test-inbox@example.com"
```

Then:

```bash
python src/main.py
```

---

## 4. Push to GitHub (first-time setup)

Replace `YOUR_GITHUB_USERNAME` with your actual GitHub username:

```bash
git init
git add .
git commit -m "Phase 0: scaffold + Phase 1: news fetch"
gh repo create YOUR_GITHUB_USERNAME/navguide-maritime-brief --public --source=. --remote=origin --push
```

If `gh` is not authenticated, create the repo manually on github.com then:

```bash
git remote add origin https://github.com/YOUR_GITHUB_USERNAME/navguide-maritime-brief.git
git branch -M main
git push -u origin main
```
