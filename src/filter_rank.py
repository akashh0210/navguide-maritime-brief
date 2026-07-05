"""Phase 2 - Dedupe, cluster, and rank raw articles into LLM-ready candidates.

Runnable standalone:  python src/filter_rank.py
"""

import logging
import os
import re
import sys
from datetime import datetime, timezone

# Allow running as a script from the repo root or the src/ directory.
sys.path.insert(0, os.path.dirname(__file__))
from news_sources import fetch_all

log = logging.getLogger(__name__)

# Keywords used for relevance scoring. Each hit adds 1 point (capped at 5).
_RANK_KEYWORDS = [
    "shipowner", "port", "inspection", "detention", "imo", "sanctions",
    "collision", "grounding", "casualty", "vessel", "shipping", "maritime",
    "tanker", "bulk carrier", "container ship", "flag state",
    "port state control", "psc", "marpol", "solas", "gt",
]

# Keywords that flag a story as a potential major-incident entry.
# The incident section in the brief covers collisions, groundings, detentions,
# and sanctions - these are the signal words for that category.
_INCIDENT_KEYWORDS = [
    "collision", "grounding", "detained", "detention", "sanctions",
    "casualty", "fire", "sinking", "sank", "aground", "arrested",
    "missing crew", "rescue", "abandon ship",
]

_MAX_CANDIDATES = 15
_MIN_USABLE_NON_INCIDENT = 5
_DEDUPE_THRESHOLD = 0.50   # Jaccard similarity above this = same story
_MAX_PER_CLUSTER = 2       # diversity cap: max articles from one topic cluster


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

# Common English stopwords plus maritime filler that pollutes token comparison.
_STOPWORDS = {
    "a", "an", "the", "in", "on", "at", "of", "for", "to", "and", "or",
    "by", "is", "was", "are", "with", "from", "as", "its", "it", "be",
    "has", "have", "had", "over", "after", "into", "amid", "about",
    "new", "says", "say", "said", "one", "two", "three",
}


def _normalize(title: str) -> str:
    """Lowercase, strip punctuation, strip trailing source attributions."""
    t = title.lower()
    t = re.sub(r"[^\w\s]", " ", t)
    # Google News often appends " - Reuters" or " - TradeWinds" etc.; remove it.
    t = re.sub(r"\s+-\s+\w[\w\s]{0,30}$", "", t)
    return " ".join(t.split())


def _tokens(text: str) -> set[str]:
    return {w for w in text.split() if w not in _STOPWORDS and len(w) > 2}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def _dedupe(articles: list[dict]) -> list[dict]:
    """Remove near-duplicate articles (same story from multiple outlets).

    Comparison: Jaccard similarity of normalized title token sets.
    When a duplicate is found, the entry with the longer snippet is kept
    (more context for the LLM). O(n^2) but n is always well under 300.
    """
    kept: list[dict] = []
    for art in articles:
        norm = _normalize(art["title"])
        toks = _tokens(norm)
        duplicate_of = None
        for k in kept:
            if _jaccard(toks, k["_tokens"]) >= _DEDUPE_THRESHOLD:
                duplicate_of = k
                break
        if duplicate_of is None:
            art["_tokens"] = toks
            kept.append(art)
        else:
            # Prefer the version with more snippet text.
            if len(art.get("snippet", "")) > len(duplicate_of.get("snippet", "")):
                idx = kept.index(duplicate_of)
                art["_tokens"] = toks
                kept[idx] = art
    return kept


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _score(art: dict, now: datetime) -> float:
    """Recency score (0-7) + keyword score (0-5) = max 12.

    Recency: 7 points for an article published today, minus 1 per day of age.
    Keyword: +1 for each _RANK_KEYWORDS hit in title or snippet, capped at 5.
    Transparent formula so results are auditable in the standalone run output.
    """
    age_days = (now - art["published"]).total_seconds() / 86400
    recency = max(0.0, 7.0 - age_days)

    haystack = (art["title"] + " " + art.get("snippet", "")).lower()
    kw_hits = sum(1 for kw in _RANK_KEYWORDS if kw in haystack)
    keyword_score = min(kw_hits, 5)

    return round(recency + keyword_score, 2)


# ---------------------------------------------------------------------------
# Topic clustering
# ---------------------------------------------------------------------------

def _cluster_key(art: dict) -> str:
    """Return a rough cluster identifier from the two lowest-sorted content tokens.

    Purpose: prevent one big story (e.g. a single port deal covered by five
    outlets after near-deduplication) from filling the candidate list.
    Deviation from architecture: architecture says "key entities/keywords"
    without specifying an algorithm. Using sorted token pairs avoids adding
    an NLP/NER dependency. Cluster collisions (unrelated articles sharing two
    common words) are rare and acceptable at this scale.
    """
    toks = sorted(art.get("_tokens", set()))
    return " ".join(toks[:2]) if len(toks) >= 2 else (toks[0] if toks else "")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def filter_and_rank(articles: list[dict]) -> dict:
    """Dedupe, cluster, rank articles and return the candidate sets for Phase 3.

    Returns a dict with:
        candidates       - top _MAX_CANDIDATES articles (with "score" key added),
                           diversity-capped at _MAX_PER_CLUSTER per topic cluster.
        incident_candidates - subset of candidates whose title/snippet matches
                           _INCIDENT_KEYWORDS; used to focus the major_incidents
                           section of the brief.
        low_volume       - True when fewer than _MIN_USABLE_NON_INCIDENT
                           non-incident stories remain after filtering.
    """
    if not articles:
        log.warning("filter_and_rank received 0 articles - nothing to rank")
        return {"candidates": [], "incident_candidates": [], "low_volume": True}

    deduped = _dedupe(articles)
    log.info("Dedupe: %d raw -> %d unique articles", len(articles), len(deduped))

    now = datetime.now(timezone.utc)
    for art in deduped:
        art["score"] = _score(art, now)

    deduped.sort(key=lambda a: a["score"], reverse=True)

    # Apply topic-cluster diversity cap before finalising candidates.
    # Rule: at most _MAX_PER_CLUSTER articles from any one cluster enter the
    # candidate list. Articles are already sorted by score, so we keep the
    # highest-scoring ones from each cluster.
    cluster_counts: dict[str, int] = {}
    candidates: list[dict] = []
    for art in deduped:
        ck = _cluster_key(art)
        if cluster_counts.get(ck, 0) < _MAX_PER_CLUSTER:
            candidates.append(art)
            cluster_counts[ck] = cluster_counts.get(ck, 0) + 1
        if len(candidates) >= _MAX_CANDIDATES:
            break

    # Classify incident candidates from within the candidate list so that the
    # Gemini prompt can focus on this subset for the major_incidents section.
    incident_candidates = [
        art for art in candidates
        if any(
            kw in (art["title"] + " " + art.get("snippet", "")).lower()
            for kw in _INCIDENT_KEYWORDS
        )
    ]

    non_incident = [a for a in candidates if a not in incident_candidates]
    low_volume = len(non_incident) < _MIN_USABLE_NON_INCIDENT

    if low_volume:
        log.warning(
            "low_volume=True: only %d non-incident stories after dedup/filter",
            len(non_incident),
        )

    # Drop the internal _tokens field before returning - not needed downstream.
    for art in candidates:
        art.pop("_tokens", None)

    log.info(
        "filter_and_rank done: %d candidates, %d incident, low_volume=%s",
        len(candidates),
        len(incident_candidates),
        low_volume,
    )
    return {
        "candidates": candidates,
        "incident_candidates": incident_candidates,
        "low_volume": low_volume,
    }


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    raw = fetch_all()
    result = filter_and_rank(raw)

    candidates = result["candidates"]
    incidents = result["incident_candidates"]

    print(f"\n{'='*65}")
    print(f"RANKED CANDIDATES  ({len(candidates)} articles, low_volume={result['low_volume']})")
    print(f"{'='*65}\n")
    for i, art in enumerate(candidates, 1):
        inc_tag = " [INCIDENT]" if art in incidents else ""
        print(f"  {i:2d}. score={art['score']:5.2f}  [{art['published'].strftime('%Y-%m-%d')}]{inc_tag}")
        print(f"      {art['title']}")
        print(f"      Source: {art['source']}  |  Feed: {art['query']}")
        print()

    print(f"\n{'='*65}")
    print(f"INCIDENT CANDIDATES  ({len(incidents)} articles)")
    print(f"{'='*65}\n")
    for art in incidents:
        print(f"  score={art['score']:5.2f}  [{art['published'].strftime('%Y-%m-%d')}]")
        print(f"  {art['title']}")
        print(f"  {art['link']}")
        print()

    if result["low_volume"]:
        print("*** LOW VOLUME FLAG SET - fewer than 5 non-incident stories ***")
