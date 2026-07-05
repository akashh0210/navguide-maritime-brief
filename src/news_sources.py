"""Phase 1 - Fetch maritime news from Google News RSS.

Runnable standalone:  python src/news_sources.py
"""

import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

import feedparser
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

log = logging.getLogger(__name__)

# Google News RSS - no API key required, no rate-limit signup.
# hl/gl/ceid pins results to English (India) for relevant maritime coverage.
_BASE_URL = "https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"

# Each query is fetched as an independent feed so one failure does not cascade.
# Query selection follows ARCHITECTURE.md Phase 1 exactly.
QUERIES = [
    "shipowners maritime shipping",
    "port operations port project",
    "marine casualty collision grounding vessel",
    "IMO regulation sanctions maritime",
    "vessel detention port state control",
]

_CUTOFF_DAYS = 7


def _clean_html(raw: str) -> str:
    return BeautifulSoup(raw, "html.parser").get_text(separator=" ").strip()


def _parse_date(entry: dict) -> datetime | None:
    """Return a UTC-aware datetime from a feedparser entry, or None if unparseable."""
    for field in ("published", "updated"):
        raw = entry.get(field)
        if raw:
            try:
                dt = dateparser.parse(raw)
                if dt is not None:
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    return dt.astimezone(timezone.utc)
            except Exception:
                pass
    return None


def fetch_all() -> list[dict]:
    """Fetch articles from all configured queries.

    Returns a combined list of article dicts, all within the last 7 days.
    A source that errors or returns nothing is skipped with a warning - the
    remaining sources still run so a single outage never kills the pipeline.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=_CUTOFF_DAYS)
    articles: list[dict] = []

    for query in QUERIES:
        url = _BASE_URL.format(query=quote_plus(query))
        try:
            feed = feedparser.parse(url)

            # feedparser sets bozo=True on malformed XML; still try entries if present.
            if feed.bozo and not feed.entries:
                log.warning("WARN: source '%s' returned a malformed/empty feed - skipping", query)
                continue

            added = 0
            for entry in feed.entries:
                pub_date = _parse_date(entry)

                if pub_date is None:
                    # Cannot determine age - include conservatively rather than silently drop.
                    pub_date = datetime.now(timezone.utc)
                    log.debug("No parseable date for '%s' - assuming now", entry.get("title", ""))

                if pub_date < cutoff:
                    continue  # older than 7 days

                # entry.source is a dict in feedparser; fall back to feed title or "Unknown".
                source = (
                    entry.get("source", {}).get("title")
                    or feed.feed.get("title", "Unknown")
                )

                articles.append({
                    "title": entry.get("title", "").strip(),
                    "link": entry.get("link", ""),
                    "published": pub_date,
                    "source": source,
                    "snippet": _clean_html(entry.get("summary", "")),
                    "query": query,
                })
                added += 1

            log.info("INFO: query='%s' - %d articles within last %d days", query, added, _CUTOFF_DAYS)

        except Exception as exc:
            log.warning("WARN: source '%s' failed (%s) - skipping", query, exc)
            continue

    return articles


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    results = fetch_all()
    results.sort(key=lambda a: a["published"], reverse=True)

    print(f"\n{'='*60}")
    print(f"Fetched {len(results)} articles - all within the last {_CUTOFF_DAYS} days")
    print(f"{'='*60}\n")

    for a in results:
        print(f"  [{a['published'].strftime('%Y-%m-%d')}]  {a['title']}")
        print(f"    Source : {a['source']}")
        print(f"    Query  : {a['query']}")
        print(f"    Link   : {a['link']}")
        if a["snippet"]:
            preview = a["snippet"][:120].replace("\n", " ")
            print(f"    Snippet: {preview}...")
        print()

    print(f"Total: {len(results)}")
