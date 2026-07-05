"""NavGuide Weekly Maritime Intelligence Brief - full pipeline orchestrator.

Run locally:    python src/main.py   (loads .env automatically)
GitHub Actions: invoked by .github/workflows/weekly-brief.yml
"""

import logging
import os
import sys

# Sub-modules live in the same directory; allow imports from either the repo
# root or the src/ directory.
sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def main() -> None:
    # Load .env for local testing. GitHub Actions provides env vars via Secrets.
    # load_dotenv() returns True only when a .env file is actually found; on the
    # GitHub runner no .env file exists and the call is a silent no-op, so the
    # secrets already injected by the workflow env: block are used directly.
    try:
        from dotenv import load_dotenv
        if load_dotenv():
            log.info("Loaded .env (local mode)")
    except ImportError:
        pass  # python-dotenv not installed; env vars must already be set

    log.info("=== NavGuide Weekly Maritime Intelligence Brief - pipeline starting ===")

    # ------------------------------------------------------------------
    # Phase 1: Fetch
    # ------------------------------------------------------------------
    log.info("--- Phase 1: fetching news sources ---")
    from news_sources import fetch_all
    raw_articles = fetch_all()
    log.info("Phase 1 complete: %d raw articles", len(raw_articles))

    # ------------------------------------------------------------------
    # Phase 2: Filter, dedupe, rank
    # ------------------------------------------------------------------
    log.info("--- Phase 2: deduplicating and ranking ---")
    from filter_rank import filter_and_rank
    ranked = filter_and_rank(raw_articles)
    log.info(
        "Phase 2 complete: %d candidates, %d incident candidates, low_volume=%s",
        len(ranked["candidates"]),
        len(ranked["incident_candidates"]),
        ranked["low_volume"],
    )

    # ------------------------------------------------------------------
    # Phase 3: Gemini enrichment
    # ------------------------------------------------------------------
    log.info("--- Phase 3: Gemini enrichment ---")
    from enrich import call_gemini
    brief = call_gemini(
        candidates=ranked["candidates"],
        incident_candidates=ranked["incident_candidates"],
        low_volume=ranked["low_volume"],
    )
    fallback = brief.get("fallback_used", False)
    log.info(
        "Phase 3 complete: %d top stories, %d incidents, fallback=%s",
        len(brief.get("top_stories", [])),
        len(brief.get("major_incidents", [])),
        fallback,
    )

    # ------------------------------------------------------------------
    # Phase 4: Build + send email
    # Even when Phase 3 fell back, we send - the email is labelled so the
    # recipient can see the degraded state rather than receiving nothing.
    # ------------------------------------------------------------------
    log.info("--- Phase 4: building and sending email ---")
    from emailer import send_email
    send_email(brief)
    log.info("Phase 4 complete: email delivered.")

    log.info("=== Pipeline complete ===")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log.exception("Pipeline failed: %s", exc)
        sys.exit(1)
