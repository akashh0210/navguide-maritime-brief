"""Phase 3 - Enrich: single Gemini call that produces the three brief sections.

Runnable standalone:  python src/enrich.py
Requires env var:     GEMINI_API_KEY
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(__file__))
from news_sources import fetch_all
from filter_rank import filter_and_rank

log = logging.getLogger(__name__)

# Model as specified in ARCHITECTURE.md.
# google-genai 2.10.0 accepts "gemini-2.5-flash" as a stable alias.
# If the API returns a model-not-found error, update to "gemini-2.0-flash".
_MODEL = "gemini-2.5-flash"


# ---------------------------------------------------------------------------
# Response schema (Pydantic)
# Used as response_schema= in GenerateContentConfig so Gemini is forced to
# return valid JSON matching this shape. Confirmed usable in google-genai
# 2.10.0: response_schema accepts Union[dict, type, Schema, ...] per
# GenerateContentConfig.model_fields inspection.
# ---------------------------------------------------------------------------

class _TopStory(BaseModel):
    title: str
    two_line_summary: str
    link: str


class _MajorIncident(BaseModel):
    vessel_or_headline: str
    incident_type: str
    two_line_summary: str
    link: str


class _OpportunitySignal(BaseModel):
    headline: str
    why_it_matters: str


class _BriefOutput(BaseModel):
    top_stories: list[_TopStory]
    major_incidents: list[_MajorIncident]
    # Optional allows null; Gemini honours this when no signal qualifies.
    opportunity_signal: Optional[_OpportunitySignal]


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def _format_articles(articles: list[dict], label: str) -> str:
    """Format article dicts as a numbered text block for the prompt."""
    if not articles:
        return f"=== {label} ===\n[none provided]\n"
    lines = [f"=== {label} ==="]
    for i, a in enumerate(articles, 1):
        lines.append(
            f"[{i}] TITLE:   {a['title']}\n"
            f"    DATE:    {a['published'].strftime('%Y-%m-%d')}\n"
            f"    SOURCE:  {a['source']}\n"
            f"    LINK:    {a['link']}\n"
            f"    SNIPPET: {a.get('snippet', '')[:300]}"
        )
    return "\n".join(lines)


def _build_prompt(
    candidates: list[dict],
    incident_candidates: list[dict],
    low_volume: bool,
) -> str:
    general_block = _format_articles(candidates, "ALL CANDIDATE ARTICLES (ranked by relevance)")
    incident_block = _format_articles(
        incident_candidates,
        "INCIDENT-FLAGGED ARTICLES (subset of above; use for major_incidents section)",
    )
    low_vol_note = (
        "\nIMPORTANT: The weekly fetch returned fewer than 5 non-incident stories. "
        "Reflect this honestly in top_stories. Do NOT pad with off-topic content.\n"
        if low_volume else ""
    )

    return f"""You are the editorial engine for NavGuide Weekly Maritime Intelligence Brief.
NavGuide Solutions is a maritime consulting firm serving shipowners, port operators, and shipping companies.
{low_vol_note}
Your job: analyse the articles below and return ONE JSON object with EXACTLY these three keys:
  top_stories, major_incidents, opportunity_signal

=== STRICT RULES ===
1. Use ONLY the articles provided below. Never invent facts, vessel names, tonnage, or dates.
2. Copy every LINK verbatim from the source article. Never modify, shorten, or reconstruct a link.
3. If a section has no qualifying items, return an empty list (top_stories, major_incidents) or null (opportunity_signal). Never fabricate filler.
4. Summaries must be factual and plain. No hype, no marketing language.

=== SECTION DEFINITIONS ===

top_stories  (list, up to 5 items):
  Each item: {{"title": "...", "two_line_summary": "...", "link": "..."}}
  - Pick the 5 most significant and DIVERSE maritime stories from ALL CANDIDATE ARTICLES.
  - two_line_summary = EXACTLY 2 sentences, factual, plain.
  - If two candidates describe the same event (same vessel + same day + same location), keep only the better-sourced one and pull in the next best story.

major_incidents  (list, any length including empty):
  Each item: {{"vessel_or_headline": "...", "incident_type": "...", "two_line_summary": "...", "link": "..."}}

  INCLUSION RULES - all three conditions must be met:
    (a) Concrete action: a specific vessel or fleet was physically or legally affected
        (collision, grounding, fire, sinking, detention by port state control, named vessel sanctioned).
        EXCLUDE: general policy discussion, "could hit tanker rates", "may impose sanctions".
    (b) Large vessel: the vessel is OVER 10,000 GT.
        Count as over 10,000 GT: bulk carrier, capesize, panamax, kamsarmax, supramax,
        VLCC, suezmax, aframax, handymax tanker, large container ship, boxship, LNG/LPG carrier,
        car carrier / PCTC, cruise ship.
        Count as under 10,000 GT (EXCLUDE): fishing vessel, small ferry, tug, barge,
        yacht, patrol boat, small general cargo.
        If vessel class is genuinely ambiguous, INCLUDE and append "(tonnage not confirmed)"
        to incident_type - do not silently drop a real incident.
    (c) Within 7 days: use the article DATE field to confirm recency.

  (d) Real outcome, not a near-miss: near-miss, avoidance, and "prevented" events
      do NOT qualify. A ship that avoided a collision, a crew that prevented a fire,
      or a hijacking that was repelled before boarding does NOT go here. Only include
      events where the vessel was physically damaged, grounded, detained, or subject
      to a concrete legal / sanctions action that took effect.

  Characterise each incident from the article content, not from which query label it
  arrived under. Do not assume "grounding" just because it came via the grounding query.

  Empty list [] is a valid and honest answer.

opportunity_signal  (object or null):
  {{"headline": "...", "why_it_matters": "..."}}
  - One story that represents a business opening for NavGuide Solutions.
  - why_it_matters = 2-3 sentences for a founder / managing partner:
    what the signal is, and the specific consulting angle NavGuide could pursue.
    Be concrete, not generic ("NavGuide could offer X to Y because Z").
  - Return null if no story qualifies.

=== ARTICLES ===

{general_block}

{incident_block}

=== OUTPUT ===
Return ONLY the raw JSON object. No markdown fences, no prose, no extra keys.
"""


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate(data: object) -> None:
    """Raise ValueError if the response does not match the expected schema."""
    if not isinstance(data, dict):
        raise ValueError(f"Expected dict, got {type(data).__name__}")

    required = {"top_stories", "major_incidents", "opportunity_signal"}
    missing = required - data.keys()
    if missing:
        raise ValueError(f"Missing keys: {missing}")

    if not isinstance(data["top_stories"], list):
        raise ValueError("top_stories must be a list")
    if not isinstance(data["major_incidents"], list):
        raise ValueError("major_incidents must be a list")

    for i, item in enumerate(data["top_stories"]):
        for k in ("title", "two_line_summary", "link"):
            if k not in item:
                raise ValueError(f"top_stories[{i}] missing key '{k}'")

    for i, item in enumerate(data["major_incidents"]):
        for k in ("vessel_or_headline", "incident_type", "two_line_summary", "link"):
            if k not in item:
                raise ValueError(f"major_incidents[{i}] missing key '{k}'")

    opp = data["opportunity_signal"]
    if opp is not None:
        if not isinstance(opp, dict):
            raise ValueError("opportunity_signal must be a dict or null")
        for k in ("headline", "why_it_matters"):
            if k not in opp:
                raise ValueError(f"opportunity_signal missing key '{k}'")


# ---------------------------------------------------------------------------
# Fallback builder
# ---------------------------------------------------------------------------

def _build_fallback(candidates: list[dict], incident_candidates: list[dict]) -> dict:
    """Plain candidate list used when Gemini is unavailable or returns bad output.

    Phase 4 checks fallback_used=True and labels the email clearly so the
    evaluator sees honest degradation rather than silence.
    """
    top = [
        {
            "title": a["title"],
            "two_line_summary": "(LLM unavailable - automated summary not generated)",
            "link": a["link"],
        }
        for a in candidates[:5]
    ]
    incidents = [
        {
            "vessel_or_headline": a["title"],
            "incident_type": "unclassified",
            "two_line_summary": "(LLM unavailable - automated summary not generated)",
            "link": a["link"],
        }
        for a in incident_candidates
    ]
    return {
        "top_stories": top,
        "major_incidents": incidents,
        "opportunity_signal": None,
        "fallback_used": True,
    }


# ---------------------------------------------------------------------------
# Main Gemini call
# ---------------------------------------------------------------------------

def call_gemini(
    candidates: list[dict],
    incident_candidates: list[dict],
    low_volume: bool,
) -> dict:
    """Call Gemini to produce the three brief sections.

    Attempts the call up to 2 times. Falls back to a plain candidate list
    if both attempts fail or return unvalidatable output.

    Returns a dict with keys: top_stories, major_incidents, opportunity_signal,
    and fallback_used (bool).
    """
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        log.error("GEMINI_API_KEY env var not set - using plain-headline fallback")
        result = _build_fallback(candidates, incident_candidates)
        return result

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    prompt = _build_prompt(candidates, incident_candidates, low_volume)

    # Structured output config - three fixes for the truncation/parse problem:
    #
    # 1. response_schema=_BriefOutput: forces Gemini to emit valid JSON
    #    matching the Pydantic schema, so the response is always parseable.
    #    Requires response_mime_type="application/json" (confirmed 2.10.0).
    #
    # 2. thinking_budget=0: gemini-2.5-flash has thinking enabled by default.
    #    Thinking tokens consume the output budget first, leaving insufficient
    #    tokens for the full JSON answer and causing mid-string truncation.
    #    Setting thinking_budget=0 disables thinking so the full budget goes
    #    to the answer. ThinkingConfig.thinking_budget confirmed in 2.10.0.
    #
    # 3. max_output_tokens=8192: headroom so even a large candidate set
    #    cannot hit the limit and truncate the response.
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=_BriefOutput,
        thinking_config=types.ThinkingConfig(thinking_budget=0),
        temperature=0.3,
        max_output_tokens=8192,
    )

    last_exc: Exception | None = None

    for attempt in range(1, 3):
        try:
            log.info("Gemini call attempt %d/2 ...", attempt)
            response = client.models.generate_content(
                model=_MODEL,
                contents=prompt,
                config=config,
            )
            raw = response.text
            if not raw or not raw.strip():
                raise ValueError("Gemini returned an empty response")

            # Strip markdown code fences in case the model wraps the JSON
            # despite response_mime_type instructing it not to.
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[-1]  # drop opening fence line
                cleaned = cleaned.rsplit("```", 1)[0]  # drop closing fence
                cleaned = cleaned.strip()

            try:
                data = json.loads(cleaned)
            except json.JSONDecodeError:
                # Log the raw text so the cause of any future failure is visible
                # in the GitHub Actions log without having to re-run.
                log.warning(
                    "Raw Gemini response (first 800 chars): %s",
                    cleaned[:800],
                )
                raise

            _validate(data)
            data.setdefault("fallback_used", False)
            log.info("Gemini call attempt %d succeeded", attempt)
            return data

        except json.JSONDecodeError as exc:
            last_exc = exc
            log.warning(
                "Attempt %d: Gemini returned non-JSON (%s) - %s",
                attempt,
                type(exc).__name__,
                "retrying" if attempt < 2 else "giving up",
            )
        except ValueError as exc:
            last_exc = exc
            log.warning(
                "Attempt %d: validation failed (%s) - %s",
                attempt,
                exc,
                "retrying" if attempt < 2 else "giving up",
            )
        except Exception as exc:
            last_exc = exc
            log.warning(
                "Attempt %d: API error (%s: %s) - %s",
                attempt,
                type(exc).__name__,
                str(exc)[:120],
                "retrying" if attempt < 2 else "giving up",
            )

    log.error(
        "Gemini failed after 2 attempts (last: %s) - using plain-headline fallback",
        last_exc,
    )
    return _build_fallback(candidates, incident_candidates)


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Load .env for local testing. In GitHub Actions, env vars come from Secrets.
    try:
        from dotenv import load_dotenv
        load_dotenv()
        log.info("Loaded .env (local mode)")
    except ImportError:
        pass  # python-dotenv not installed; env vars must be set manually

    log.info("Phase 1: fetching news sources ...")
    raw_articles = fetch_all()

    log.info("Phase 2: filter and rank ...")
    ranked = filter_and_rank(raw_articles)

    log.info(
        "Phase 3: calling Gemini (%s candidates, %s incident, low_volume=%s) ...",
        len(ranked["candidates"]),
        len(ranked["incident_candidates"]),
        ranked["low_volume"],
    )
    result = call_gemini(
        candidates=ranked["candidates"],
        incident_candidates=ranked["incident_candidates"],
        low_volume=ranked["low_volume"],
    )

    fallback = result.get("fallback_used", False)
    if fallback:
        print("\n*** FALLBACK MODE - LLM step unavailable ***")
        print("*** Email will be labelled [FALLBACK - LLM step unavailable] ***\n")

    SEP = "=" * 65

    print(f"\n{SEP}")
    print("TOP STORIES")
    print(SEP)
    for i, s in enumerate(result.get("top_stories", []), 1):
        print(f"\n{i}. {s['title']}")
        print(f"   Summary : {s['two_line_summary']}")
        print(f"   Link    : {s['link']}")

    print(f"\n{SEP}")
    print("MAJOR INCIDENTS  (vessels over 10,000 GT)")
    print(SEP)
    incidents = result.get("major_incidents", [])
    if not incidents:
        print("\n  No qualifying incidents this week.")
    for inc in incidents:
        print(f"\n  Vessel/headline : {inc['vessel_or_headline']}")
        print(f"  Incident type   : {inc['incident_type']}")
        print(f"  Summary         : {inc['two_line_summary']}")
        print(f"  Link            : {inc['link']}")

    print(f"\n{SEP}")
    print("OPPORTUNITY SIGNAL")
    print(SEP)
    opp = result.get("opportunity_signal")
    if opp:
        print(f"\n  Headline       : {opp['headline']}")
        print(f"  Why it matters : {opp['why_it_matters']}")
    else:
        print("\n  No opportunity signal identified this week.")

    print(f"\n{SEP}")
    print(f"fallback_used = {fallback}")
    print(SEP)
