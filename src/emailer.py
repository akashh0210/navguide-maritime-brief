"""Phase 4 - Build and send the HTML maritime brief email.

Not runnable standalone - requires Phase 3 output. Entry point: python src/main.py
"""

import html as _html
import logging
import os
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

log = logging.getLogger(__name__)

# Colour palette - used throughout HTML generation.
_NAVY = "#1B3A5C"
_NAVY_LIGHT = "#B0C8E4"
_BG_PAGE = "#F0F4F8"
_BG_SECTION = "#EEF3F8"
_LINK = "#1B6CBF"
_TEXT = "#333333"
_TEXT_MUTED = "#666666"
_RED = "#C0392B"
_FOOTER_BG = "#F8F9FA"
_BORDER = "#E5E9F0"


# ---------------------------------------------------------------------------
# HTML helpers - all user-supplied text must pass through _e() before insertion
# ---------------------------------------------------------------------------

def _e(text: str) -> str:
    """HTML-escape a string so titles/summaries cannot break the markup."""
    return _html.escape(str(text), quote=True)


def _section_header(title: str, subtitle: str = "") -> str:
    sub_html = (
        f'<div style="color:#5A7A99;font-size:12px;margin-top:3px;">{_e(subtitle)}</div>'
        if subtitle else ""
    )
    return f"""
      <tr>
        <td style="background:{_BG_SECTION};padding:14px 32px;border-top:3px solid {_NAVY};">
          <span style="color:{_NAVY};font-size:14px;font-weight:bold;letter-spacing:0.8px;text-transform:uppercase;">{_e(title)}</span>
          {sub_html}
        </td>
      </tr>"""


def _story_row(num: int, story: dict) -> str:
    title = _e(story.get("title", ""))
    summary = _e(story.get("two_line_summary", ""))
    link = story.get("link", "#")   # URLs are not HTML-escaped (angle brackets/& in URLs are legal)
    return f"""
      <tr>
        <td style="padding:18px 32px;border-bottom:1px solid {_BORDER};">
          <div style="font-size:12px;color:#9AAABB;margin-bottom:4px;font-weight:bold;">{num}</div>
          <a href="{link}" style="color:{_LINK};font-size:16px;font-weight:600;text-decoration:none;line-height:1.4;">{title}</a>
          <div style="color:{_TEXT};font-size:14px;line-height:1.65;margin-top:8px;">{summary}</div>
          <div style="margin-top:10px;">
            <a href="{link}" style="color:{_LINK};font-size:12px;text-decoration:underline;">Read source article</a>
          </div>
        </td>
      </tr>"""


def _incident_row(inc: dict) -> str:
    headline = _e(inc.get("vessel_or_headline", ""))
    inc_type = _e(inc.get("incident_type", "").upper())
    summary = _e(inc.get("two_line_summary", ""))
    link = inc.get("link", "#")
    return f"""
      <tr>
        <td style="padding:18px 32px;border-bottom:1px solid {_BORDER};">
          <span style="display:inline-block;background:{_RED};color:#ffffff;font-size:10px;font-weight:bold;padding:2px 8px;border-radius:3px;letter-spacing:0.5px;margin-bottom:7px;">{inc_type}</span>
          <div style="color:{_NAVY};font-size:15px;font-weight:600;margin-bottom:8px;">{headline}</div>
          <div style="color:{_TEXT};font-size:14px;line-height:1.65;">{summary}</div>
          <div style="margin-top:10px;">
            <a href="{link}" style="color:{_LINK};font-size:12px;text-decoration:underline;">Read source article</a>
          </div>
        </td>
      </tr>"""


# ---------------------------------------------------------------------------
# HTML builder
# ---------------------------------------------------------------------------

def build_html(brief: dict, date_range: str, run_date: str) -> str:
    fallback = brief.get("fallback_used", False)

    fallback_banner = ""
    if fallback:
        fallback_banner = f"""
      <tr>
        <td style="background:#FFF3CD;border-left:4px solid #D4960A;padding:14px 32px;font-size:13px;color:#6D5000;">
          <strong>[FALLBACK - automated summaries unavailable this run]</strong><br>
          Headlines and links are sourced directly from news feeds without AI summarisation.
        </td>
      </tr>"""

    stories = brief.get("top_stories", [])[:5]
    story_rows = "".join(_story_row(i + 1, s) for i, s in enumerate(stories))
    if not story_rows:
        story_rows = f'<tr><td style="padding:18px 32px;color:{_TEXT_MUTED};font-size:14px;">No top stories available this week.</td></tr>'

    incidents = brief.get("major_incidents", [])
    if incidents:
        incident_rows = "".join(_incident_row(inc) for inc in incidents)
    else:
        incident_rows = f"""
      <tr>
        <td style="padding:18px 32px;color:{_TEXT_MUTED};font-size:14px;font-style:italic;">
          No major incidents involving vessels over 10,000 GT were reported this week.
        </td>
      </tr>"""

    opp = brief.get("opportunity_signal")
    if opp:
        opp_rows = f"""
      <tr>
        <td style="padding:22px 32px;">
          <div style="color:{_NAVY};font-size:16px;font-weight:600;margin-bottom:10px;">{_e(opp.get('headline', ''))}</div>
          <div style="color:{_TEXT};font-size:14px;line-height:1.7;">{_e(opp.get('why_it_matters', ''))}</div>
        </td>
      </tr>"""
    else:
        opp_rows = f'<tr><td style="padding:18px 32px;color:{_TEXT_MUTED};font-size:14px;font-style:italic;">No opportunity signal identified this week.</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>NavGuide Weekly Maritime Intelligence Brief</title>
</head>
<body style="margin:0;padding:0;background:{_BG_PAGE};font-family:Arial,Helvetica,sans-serif;">

<table width="100%" cellpadding="0" cellspacing="0" style="background:{_BG_PAGE};">
  <tr><td align="center" style="padding:28px 12px;">

    <table width="620" cellpadding="0" cellspacing="0" style="max-width:620px;width:100%;background:#ffffff;border-radius:6px;">

      <!-- Header -->
      <tr>
        <td style="background:{_NAVY};padding:36px 32px;text-align:center;border-radius:6px 6px 0 0;">
          <div style="color:#ffffff;font-size:21px;font-weight:bold;letter-spacing:0.5px;line-height:1.3;">NavGuide Weekly Maritime Intelligence Brief</div>
          <div style="color:{_NAVY_LIGHT};font-size:13px;margin-top:10px;">Coverage period: {_e(date_range)}</div>
        </td>
      </tr>
      {fallback_banner}

      {_section_header("Top Stories")}
      {story_rows}

      {_section_header("Major Incidents", "Vessels over 10,000 GT - past 7 days")}
      {incident_rows}

      {_section_header("Opportunity Signal", "Business intelligence for NavGuide Solutions")}
      {opp_rows}

      <!-- Footer -->
      <tr>
        <td style="background:{_FOOTER_BG};padding:20px 32px;border-top:1px solid {_BORDER};border-radius:0 0 6px 6px;text-align:center;">
          <div style="color:#999999;font-size:11px;line-height:1.7;">
            Generated automatically by the NavGuide Maritime Brief Agent on {_e(run_date)}.<br>
            Sources are public maritime news RSS feeds. Links open original articles.
          </div>
        </td>
      </tr>

    </table>
  </td></tr>
</table>

</body>
</html>"""


# ---------------------------------------------------------------------------
# Plain-text builder
# ---------------------------------------------------------------------------

def build_plain(brief: dict, date_range: str, run_date: str) -> str:
    """Plain-text fallback for email clients that do not render HTML."""
    lines = [
        "NAVGUIDE WEEKLY MARITIME INTELLIGENCE BRIEF",
        f"Coverage period: {date_range}",
        "",
    ]

    if brief.get("fallback_used"):
        lines += [
            "[FALLBACK - automated summaries unavailable this run]",
            "Headlines and links are sourced directly from news feeds.",
            "",
        ]

    lines += ["=" * 62, "TOP STORIES", "=" * 62, ""]
    for i, s in enumerate(brief.get("top_stories", [])[:5], 1):
        lines += [
            f"{i}. {s.get('title', '')}",
            f"   {s.get('two_line_summary', '')}",
            f"   Source: {s.get('link', '')}",
            "",
        ]
    if not brief.get("top_stories"):
        lines += ["No top stories available this week.", ""]

    lines += ["=" * 62, "MAJOR INCIDENTS (Vessels over 10,000 GT)", "=" * 62, ""]
    incidents = brief.get("major_incidents", [])
    if not incidents:
        lines += [
            "No major incidents involving vessels over 10,000 GT were reported this week.",
            "",
        ]
    else:
        for inc in incidents:
            lines += [
                f"[{inc.get('incident_type', '').upper()}] {inc.get('vessel_or_headline', '')}",
                f"   {inc.get('two_line_summary', '')}",
                f"   Source: {inc.get('link', '')}",
                "",
            ]

    lines += ["=" * 62, "OPPORTUNITY SIGNAL", "=" * 62, ""]
    opp = brief.get("opportunity_signal")
    if opp:
        lines += [
            opp.get("headline", ""),
            "",
            opp.get("why_it_matters", ""),
            "",
        ]
    else:
        lines += ["No opportunity signal identified this week.", ""]

    lines += [
        "-" * 62,
        f"Generated automatically by the NavGuide Maritime Brief Agent on {run_date}.",
        "Sources are public maritime news RSS feeds.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Send
# ---------------------------------------------------------------------------

def send_email(brief: dict) -> None:
    """Build and send the brief email via Gmail SMTP SSL (port 465).

    Raises RuntimeError on SMTP failure so the GitHub Actions run shows RED.
    A silent non-send is worse than a loud failure for this delivery use case.
    """
    gmail_addr = os.environ.get("GMAIL_ADDRESS", "")
    gmail_pass = os.environ.get("GMAIL_APP_PASSWORD", "")
    recipient = os.environ.get("RECIPIENT_EMAIL", "")

    if not all([gmail_addr, gmail_pass, recipient]):
        raise RuntimeError(
            "GMAIL_ADDRESS, GMAIL_APP_PASSWORD, and RECIPIENT_EMAIL must all be "
            "set as environment variables or GitHub Secrets before sending."
        )

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=7)
    date_range = f"{start.strftime('%d %b %Y')} to {now.strftime('%d %b %Y')}"
    run_date = now.strftime("%d %b %Y, %H:%M UTC")

    # Colon separator per project rules - no em dash anywhere.
    subject = f"Weekly Maritime Intelligence Brief: {date_range}"

    html_body = build_html(brief, date_range, run_date)
    plain_body = build_plain(brief, date_range, run_date)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_addr
    msg["To"] = recipient
    # Plain part first; email clients prefer the last matching part (HTML).
    msg.attach(MIMEText(plain_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    log.info("Connecting to Gmail SMTP SSL (port 465) ...")
    ctx = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as server:
            server.login(gmail_addr, gmail_pass)
            server.sendmail(gmail_addr, [recipient], msg.as_string())
        log.info("Email sent to %s | subject: %s", recipient, subject)
    except smtplib.SMTPAuthenticationError as exc:
        raise RuntimeError(
            "Gmail authentication failed. Check GMAIL_ADDRESS and GMAIL_APP_PASSWORD "
            "(must be a 16-char App Password, not your login password)."
        ) from exc
    except smtplib.SMTPException as exc:
        raise RuntimeError(f"SMTP send failed: {exc}") from exc
