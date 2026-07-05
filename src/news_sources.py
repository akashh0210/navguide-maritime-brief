"""Phase 1 - Fetch maritime news from Google News RSS and specialist RSS feeds.

Runnable standalone:  python src/news_sources.py
"""

import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

import feedparser
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

log = logging.getLogger(__name__)

# Google News RSS - no API key, no signup.
# hl/gl/ceid pins results to English (India).
_GNEWS_BASE = "https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"

# Original 3-query architecture used long AND-phrases that returned 0 results on
# Google News RSS (all words must co-occur in the same article). Replaced with
# short, single-topic queries that reliably return hits.
GOOGLE_NEWS_QUERIES = [
    # General maritime - these two were already working
    "shipowners maritime shipping",
    "port operations port project",
    # Incident coverage - split into short single-topic queries
    "ship collision",
    "vessel grounding",
    "ship detention",
    "port state control detention",
    "shipping sanctions",
    "tanker sanctions",
    "IMO regulation",
    "bulk carrier incident",
    "container ship incident",
]

# Specialist maritime publishers with dedicated incident/accident feeds.
# These bypass keyword matching entirely and reliably cover incidents.
# Each entry is (feed_url, label_for_logging).
# URLs verified against published feed paths as of project build date;
# the try/except in fetch_all() will skip any that have moved.
DIRECT_FEEDS: list[tuple[str, str]] = [
    (
        "https://gcaptain.com/category/incidents/feed/",
        "gcaptain-incidents",
    ),
    (
        "https://safety4sea.com/category/maritime-safety-security/accidents/feed/",
        "safety4sea-accidents",
    ),
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


def _entries_from_feed(url: str, label: str, cutoff: datetime) -> list[dict]:
    """Parse one RSS feed URL and return article dicts within the cutoff window.

    Raises on network/parse failure so the caller can log and continue.
    """
    feed = feedparser.parse(url)

    if feed.bozo and not feed.entries:
        raise ValueError(f"malformed/empty feed (bozo={feed.bozo_exception})")

    results: list[dict] = []
    for entry in feed.entries:
        pub_date = _parse_date(entry)

        if pub_date is None:
            # Cannot determine age - include conservatively rather than silently drop.
            pub_date = datetime.now(timezone.utc)

        if pub_date < cutoff:
            continue

        source = (
            entry.get("source", {}).get("title")
            or feed.feed.get("title", "Unknown")
        )

        results.append({
            "title": entry.get("title", "").strip(),
            "link": entry.get("link", ""),
            "published": pub_date,
            "source": source,
            "snippet": _clean_html(entry.get("summary", "")),
            "query": label,
        })

    return results


def fetch_all() -> list[dict]:
    """Fetch articles from all Google News queries and direct RSS feeds.

    Returns a combined list within the last 7 days.
    Each source is wrapped in try/except; a dead source logs a warning and is
    skipped so the rest of the pipeline always continues.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=_CUTOFF_DAYS)
    articles: list[dict] = []

    # --- Google News RSS ---
    for query in GOOGLE_NEWS_QUERIES:
        url = _GNEWS_BASE.format(query=quote_plus(query))
        label = f"goog:{query}"
        try:
            batch = _entries_from_feed(url, label, cutoff)
            articles.extend(batch)
            log.info("INFO: %-45s  %d articles", label, len(batch))
        except Exception as exc:
            log.warning("WARN: source '%s' failed (%s) - skipping", label, exc)

    # --- Specialist direct RSS feeds ---
    for feed_url, feed_label in DIRECT_FEEDS:
        try:
            batch = _entries_from_feed(feed_url, feed_label, cutoff)
            articles.extend(batch)
            log.info("INFO: %-45s  %d articles", feed_label, len(batch))
        except Exception as exc:
            log.warning("WARN: source '%s' failed (%s) - skipping", feed_label, exc)

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
