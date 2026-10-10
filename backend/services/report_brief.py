"""
Shuhul report brief: what a news report says, without a language model.

A brief is put together from the report's own words: what kind of issue
it is, the places, figures and public bodies it names, and the two lines
that carry the most of that. Nothing is rewritten, so nothing can be
made up, and it works with no outside service.

For a live report the text is fetched from the outlet when the brief is
asked for and is not kept. Only the brief is cached, for a while.

    GET /api/watch/issues/<id>/brief
    GET /api/environmental-watch/articles/<article_id>/brief
"""

import json
import re
import threading
import time
import urllib.parse

from ..db import get_watch_issue
from .environmental_watch import DISTRICT_DISPLAY_NAMES, _find_article_by_id
from .watch_ingest import (
    CATEGORIES,
    SOURCES,
    _get,
    _plain,
    classify,
    district_from_text,
    place_candidates,
)

MAX_FIGURES = 8

# Words the place finder picks up that are not places a planner can go to.
NOT_SPECIFIC = {"india", "indian", "kashmir", "kashmiri", "jammu", "jammu kashmir", "valley"}

# Lines at the top of a saved report that describe it rather than tell it.
HEADER_LINE = re.compile(r"^(?:DATE|SOURCE|URL|TITLE|AUTHOR|BY)\s*:.*$", flags=re.I | re.M)
MAX_KEY_LINES = 2
MAX_LINE_CHARS = 260
CACHE_SECONDS = 6 * 3600

# Things a figure can count, as they are written in reports.
UNITS = (
    r"trees?|saplings|chinars?|kanals?|hectares?|acres?|marlas?|"
    r"km|kms|kilometres?|kilometers?|metres?|meters?|feet|"
    r"families|households|people|persons|residents|villages|houses|structures|shops|"
    r"tonnes?|tons|cusecs|MLD|mm|percent|per cent|°C|degrees?"
)
NUMBER = r"\d[\d,]*(?:\.\d+)?(?:\s*(?:lakh|lakhs|crore|crores|thousand|million|billion))?"

FIGURE = re.compile(
    rf"(?:(?:Rs\.?|₹)\s*{NUMBER})|(?:{NUMBER}\s*(?:{UNITS})\b)|(?:{NUMBER}\s*%)",
    flags=re.I,
)

# Public bodies that turn up in environmental reporting from Kashmir, and
# the ways reports write them.
BODIES = {
    "National Green Tribunal": [r"National Green Tribunal", r"\bNGT\b"],
    "High Court": [r"High Court"],
    "Forest Department": [r"Forest Department", r"forest officials?"],
    "Pollution Control Committee": [r"Pollution Control (?:Committee|Board)", r"\bJKPCC\b", r"\bPCB\b"],
    "Lake Conservation and Management Authority": [r"Lake Conservation and Management Authority", r"\bLCMA\b", r"\bLAWDA\b"],
    "Srinagar Municipal Corporation": [r"Srinagar Municipal Corporation", r"\bSMC\b"],
    "Irrigation and Flood Control Department": [r"Irrigation (?:and|&) Flood Control", r"\bI&FC\b"],
    "National Highways Authority of India": [r"National Highways? Authority", r"\bNHAI\b"],
    "Roads and Buildings Department": [r"Roads (?:and|&) Buildings", r"\bR&B\b"],
    "Jal Shakti Department": [r"Jal Shakti"],
    "Wildlife Protection Department": [r"Wildlife (?:Protection )?Department"],
    "Srinagar Smart City": [r"Smart City"],
    "Srinagar Development Authority": [r"Srinagar Development Authority", r"\bSDA\b"],
    "Disaster Management Authority": [r"Disaster Management"],
    "Meteorological Department": [r"Meteorological (?:Department|Centre)", r"\bIMD\b", r"\bMeT\b"],
    "Comptroller and Auditor General": [r"Comptroller and Auditor General", r"\bCAG\b"],
    "Revenue Department": [r"Revenue Department"],
}

_cache = {}
_cache_lock = threading.Lock()


class BriefUnavailable(Exception):
    """The report could not be read."""


# ------------------------------------------------------------
# READING THE REPORT
# ------------------------------------------------------------

def _paragraphs(html):
    """The running text of a web page: its longer paragraphs."""
    found = re.findall(r"<p\b[^>]*>(.*?)</p>", html, flags=re.S | re.I)
    kept = [_plain(part) for part in found]
    return " ".join(part for part in kept if len(part) >= 60)


def fetch_text(source, url):
    """The text of a live report, from the outlet. Not kept."""
    base = SOURCES.get(source, {}).get("wordpress")

    if base:
        slug = urllib.parse.urlsplit(url).path.rstrip("/").split("/")[-1]
        query = urllib.parse.urlencode({"slug": slug, "_fields": "content"})
        try:
            posts = json.loads(_get(f"{base}/wp-json/wp/v2/posts?{query}"))
            if posts:
                return _plain(posts[0]["content"]["rendered"])
        except Exception:
            pass

    return _paragraphs(_get(url).decode("utf-8", errors="replace"))


# ------------------------------------------------------------
# BUILDING THE BRIEF
# ------------------------------------------------------------

def _figures(text):
    seen, found = set(), []

    for match in FIGURE.finditer(text):
        figure = re.sub(r"\s+", " ", match.group(0)).strip()
        key = figure.lower()
        if key not in seen:
            seen.add(key)
            found.append(figure)

    return found[:MAX_FIGURES]


def _bodies(text):
    return [
        name for name, patterns in BODIES.items()
        if any(re.search(pattern, text) for pattern in patterns)
    ]


def _key_lines(text, category, places, figures):
    """The lines that carry most of what the brief found, in their own order."""
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+(?=[A-Z\"'])", text)]
    sentences = [part for part in sentences if 40 <= len(part) <= 400]

    keywords = [word.lower() for word in CATEGORIES.get(category, {}).get("words", [])]
    scored = []

    for position, sentence in enumerate(sentences):
        lower = sentence.lower()
        score = (
            1.0 * sum(1 for figure in figures if figure.lower() in lower)
            + 1.5 * sum(1 for place in places if place.lower() in lower)
            + 2.0 * sum(1 for word in keywords if word in lower)
        )
        # The opening lines of a news report say what happened.
        if position < 2:
            score += 2.0
        if score > 0:
            scored.append((score, position, sentence))

    best = sorted(sorted(scored, reverse=True)[:MAX_KEY_LINES], key=lambda item: item[1])
    return [
        sentence if len(sentence) <= MAX_LINE_CHARS else sentence[:MAX_LINE_CHARS].rsplit(" ", 1)[0] + "…"
        for _, _, sentence in best
    ]


def build_brief(title, text):
    """What a report says, from its own words."""
    text = HEADER_LINE.sub("", text or "").strip()
    if len(text) < 80:
        raise BriefUnavailable("The report has too little text to summarise.")

    category, _ = classify(title, text)
    places = [
        place for place in place_candidates(title, text)
        if place.lower() not in NOT_SPECIFIC
    ][:5]
    figures = _figures(f"{title}. {text}")
    bodies = _bodies(text)
    district = district_from_text(title, text)

    return {
        "type": CATEGORIES.get(category, {}).get("label") if category else None,
        "district": DISTRICT_DISPLAY_NAMES.get(district),
        "places": places,
        "figures": figures,
        "bodies": bodies,
        "key_lines": _key_lines(text, category, places, figures),
        "words": len(text.split()),
        "method": (
            "Put together from the report's own words by fixed rules, with no language "
            "model: nothing is rewritten. Figures and names are as the report gives "
            "them, not checked. The lines shown are quoted from the report."
        ),
    }


# ------------------------------------------------------------
# API
# ------------------------------------------------------------

def register_brief_routes(app):
    from flask import jsonify

    @app.get("/api/watch/issues/<int:issue_id>/brief")
    def watch_issue_brief(issue_id):
        issue = get_watch_issue(issue_id)
        if issue is None:
            return jsonify({"error": "Report not found."}), 404

        with _cache_lock:
            cached = _cache.get(issue_id)
        if cached and time.time() - cached[0] < CACHE_SECONDS:
            return jsonify(cached[1])

        try:
            text = fetch_text(issue["source"], issue["url"])
            brief = build_brief(issue["title"], text)
        except BriefUnavailable as exc:
            return jsonify({"error": str(exc)}), 422
        except Exception:
            return jsonify({"error": "The report could not be read from its outlet just now."}), 502

        brief["title"] = issue["title"]
        brief["url"] = issue["url"]

        with _cache_lock:
            _cache[issue_id] = (time.time(), brief)
        return jsonify(brief)

    @app.get("/api/environmental-watch/articles/<article_id>/brief")
    def archive_article_brief(article_id):
        article = _find_article_by_id(article_id)
        if article is None:
            return jsonify({"error": "Report not found."}), 404

        try:
            brief = build_brief(article.title, article.text)
        except BriefUnavailable as exc:
            return jsonify({"error": str(exc)}), 422

        brief["title"] = article.title
        brief["url"] = article.url
        return jsonify(brief)
