"""
Shuhul Environmental Watch: live ingestion.

Reads three Kashmir news outlets, keeps the reports that concern the
environment, works out what kind of issue each one is and where it is,
and stores the result for the Watch map.

    Feed / search  ->  de-duplicate  ->  classify  ->  locate  ->  store

What is stored for a report is its headline, link, date, a short
excerpt and what was extracted from it. The article text is read to
classify and locate the report and is then discarded; readers are sent
to the outlet for the article itself.

A report is a claim made by its source. Nothing here verifies it.

    python -m backend.services.watch_ingest
"""

from collections import Counter
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
import json
import re
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from ..config import PROJECT_ROOT
from ..db import (
    add_watch_issue,
    get_watch_place,
    init_db,
    known_watch_urls,
    latest_watch_fetch,
    list_watch_issues,
    save_watch_place,
)
from .environmental_watch import DISTRICT_ALIASES, DISTRICT_DISPLAY_NAMES


# ------------------------------------------------------------
# SOURCES
# ------------------------------------------------------------

SOURCES = {
    "greaterkashmir": {
        "name": "Greater Kashmir",
        "feed": "https://www.greaterkashmir.com/feed",
        "wordpress": None,
    },
    "freepresskashmir": {
        "name": "Free Press Kashmir",
        "feed": "https://freepresskashmir.news/feed/",
        "wordpress": "https://freepresskashmir.news",
    },
    "kashmirlife": {
        "name": "Kashmir Life",
        "feed": "https://kashmirlife.net/feed/",
        "wordpress": "https://kashmirlife.net",
    },
}

# The feeds only carry the latest few stories, so the two WordPress
# outlets are also searched for environmental reporting.
SEARCH_TERMS = [
    "trees felled",
    "wetland",
    "flood",
    "water bodies",
    "pollution",
    "heatwave",
    "landslide",
    "road project",
]
SEARCH_RESULTS_PER_TERM = 15

USER_AGENT = "Shuhul/0.1 environmental planning research (github.com/hanaanllone/shuhul)"
REQUEST_PAUSE_SECONDS = 1.1
EXCERPT_CHARS = 240

CONTENT_NS = "{http://purl.org/rss/1.0/modules/content/}encoded"


# ------------------------------------------------------------
# ISSUE TYPES
# ------------------------------------------------------------
#
# label, the map layers worth opening for it, and the words that mark it.

CATEGORIES = {
    "tree_loss": {
        "label": "Tree loss",
        "factors": ["tree_height", "ndvi", "lst"],
        "words": [
            "trees felled", "tree felling", "felled", "axed", "axing", "chinar",
            "poplar", "deforestation", "trees cut", "cutting of trees", "timber",
            "forest land", "green cover",
        ],
    },
    "wetland_loss": {
        "label": "Wetland and water body loss",
        "factors": ["water_lost", "water_occurrence", "flood"],
        "words": [
            "wetland", "hokersar", "anchar", "wular", "dal lake", "nigeen",
            "marsh", "water body", "water bodies", "lake shrink", "floodplain",
            "flood channel", "encroachment of lake", "lake encroach",
        ],
    },
    "flooding": {
        "label": "Flooding",
        "factors": ["flood", "water_occurrence", "slope"],
        "words": [
            "flood", "inundat", "waterlog", "cloudburst", "embankment",
            "breach", "flash flood", "danger mark", "submerged",
        ],
    },
    "water_pollution": {
        "label": "Water pollution",
        "factors": ["water", "buildings"],
        "words": [
            "sewage", "effluent", "polluted water", "water pollution",
            "contaminat", "untreated", "drain into", "fish kill",
        ],
    },
    "air_pollution": {
        "label": "Air pollution",
        "factors": ["buildings", "tree_height"],
        "words": [
            "air quality", "aqi", "smog", "pm2.5", "pm10", "brick kiln",
            "air pollution", "burning of", "stubble", "dust pollution",
        ],
    },
    "waste": {
        "label": "Waste and dumping",
        "factors": ["landcover", "water"],
        "words": [
            "garbage", "dumping", "solid waste", "landfill", "achan",
            "waste management", "dump site", "littering",
        ],
    },
    "heat": {
        "label": "Heat",
        "factors": ["lst", "tree_height", "buildings"],
        "words": [
            "heatwave", "heat wave", "hottest", "record temperature",
            "scorching", "heat stress", "mercury soars",
        ],
    },
    "water_scarcity": {
        "label": "Water scarcity",
        "factors": ["water", "ndvi"],
        "words": [
            "water crisis", "dry spell", "dries up", "drought",
            "drinking water", "water shortage", "spring dry", "rainfall deficit",
        ],
    },
    "land_degradation": {
        "label": "Land degradation",
        "factors": ["slope", "landcover"],
        "words": [
            "landslide", "erosion", "illegal mining", "quarry", "riverbed mining",
            "extraction of", "land sinking", "subsidence",
        ],
    },
    "construction": {
        "label": "Construction and projects",
        "factors": ["tree_height", "flood", "lst"],
        "words": [
            "ring road", "road project", "highway", "flyover", "four-laning",
            "tender", "construction of", "smart city", "tunnel", "railway line",
        ],
    },
}

TITLE_WEIGHT = 3
MIN_RELEVANCE = 3

# An infrastructure story is only kept when it also says something
# about the environment, more than in passing.
MIN_ENVIRONMENT_MENTIONS = 2
ENVIRONMENT_WORDS = [
    "environment", "ecolog", "tree", "forest", "wetland", "flood", "pollut",
    "green", "wildlife", "ngt", "national green tribunal", "climate",
]


# ------------------------------------------------------------
# PLACES
# ------------------------------------------------------------

# Places that come up again and again in Kashmir environmental reporting.
KNOWN_PLACES = [
    "Dal Lake", "Nigeen Lake", "Anchar Lake", "Wular Lake", "Manasbal Lake",
    "Hokersar", "Jhelum", "Doodh Ganga", "Lidder", "Sindh river",
    "Bemina", "Rajbagh", "Lal Chowk", "Hazratbal", "Soura", "Nowgam",
    "Pampore", "Narbal", "Tangmarg", "Gulmarg", "Pahalgam", "Sonamarg",
    "Bangus", "Handwara", "Tral", "Doodhpathri", "Yusmarg", "Achan",
    "Zabarwan", "Dachigam", "Sopore", "Pattan", "Chadoora", "Magam",
    "Kangan", "Awantipora", "Bijbehara", "Qazigund", "Uri", "Gurez",
]

PLACE_PATTERN = re.compile(
    r"\b(?:in|at|near|from|around|of)\s+((?:[A-Z][a-z]{2,})(?:[ -][A-Z][a-z]{2,}){0,2})"
)

NOT_PLACES = {
    "Kashmir", "Jammu", "India", "Ladakh", "Government", "Monday", "Tuesday",
    "Wednesday", "Thursday", "Friday", "Saturday", "Sunday", "January",
    "February", "March", "April", "May", "June", "July", "August",
    "September", "October", "November", "December", "High Court", "Supreme Court",
    "National Green Tribunal", "Parliament", "Assembly", "Union Territory",
    "Kashmir Valley", "Pakistan", "China", "Delhi", "New Delhi", "Forest",
    "State", "Himalayan", "Himalayas", "Valley", "District", "Centre", "Police",
    "Department", "Minister", "Chief Minister", "Deputy Commissioner", "Court",
}

# Kinds of map feature a place name is allowed to resolve to.
PLACE_TYPES = {
    "city", "town", "village", "hamlet", "suburb", "neighbourhood", "quarter",
    "locality", "isolated_dwelling", "wetland", "water", "river", "stream",
    "peak", "valley", "glacier", "wood", "nature_reserve", "national_park",
    "park", "forest", "administrative",
}

# A report with no place and no district is kept only if it is plainly
# about Kashmir.
REGION_WORDS = ["kashmir", "srinagar", "jhelum"]

# "SRINAGAR:" or "Srinagar, Oct 9:" at the start of a report says where
# it was filed from, not where it is about.
DATELINE = re.compile(
    r"^\s*[A-Z][A-Za-z]+(?: [A-Z][A-Za-z]+)?(?:,\s*[A-Z][a-z]{2,8}\.?\s+\d{1,2})?\s*[:\u2013\u2014-]\s*"
)

NOMINATIM = "https://nominatim.openstreetmap.org/search"
KASHMIR_VIEWBOX = "73.7,34.9,75.7,33.3"
MAX_PLACES_PER_REPORT = 3


# ------------------------------------------------------------
# FETCHING
# ------------------------------------------------------------

_last_request = {}
_request_lock = threading.Lock()


def _get(url):
    """Fetch a URL, leaving a pause between requests to the same host."""
    host = urllib.parse.urlsplit(url).netloc

    with _request_lock:
        wait = REQUEST_PAUSE_SECONDS - (time.time() - _last_request.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        _last_request[host] = time.time()

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def _plain(html):
    text = re.sub(r"<(script|style)\b.*?</\1>", " ", html or "", flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", unescape(text)).strip()


def _iso_date(value):
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return value[:19]


def fetch_feed(source):
    """Latest reports from an outlet's RSS feed."""
    root = ET.fromstring(_get(SOURCES[source]["feed"]))
    reports = []

    for item in root.findall(".//item"):
        summary = _plain(item.findtext("description"))
        reports.append({
            "source": source,
            "url": (item.findtext("link") or "").strip(),
            "title": _plain(item.findtext("title")),
            "published_at": _iso_date(item.findtext("pubDate")),
            "summary": summary,
            "text": _plain(item.findtext(CONTENT_NS)) or summary,
        })

    return [report for report in reports if report["url"] and report["title"]]


def search_wordpress(source, term):
    """Reports matching a search term, from an outlet's public WordPress API."""
    base = SOURCES[source]["wordpress"]
    query = urllib.parse.urlencode({
        "search": term,
        "per_page": SEARCH_RESULTS_PER_TERM,
        "_fields": "date,link,title,excerpt,content",
    })
    posts = json.loads(_get(f"{base}/wp-json/wp/v2/posts?{query}"))

    return [
        {
            "source": source,
            "url": post["link"],
            "title": _plain(post["title"]["rendered"]),
            "published_at": post["date"],
            "summary": _plain(post["excerpt"]["rendered"]),
            "text": _plain(post["content"]["rendered"]),
        }
        for post in posts
    ]


# ------------------------------------------------------------
# CLASSIFYING
# ------------------------------------------------------------

def classify(title, text):
    """
    Return (category, relevance), or (None, 0) for a report that is not
    about the environment.
    """
    title_lower = title.lower()
    text_lower = text.lower()
    scores = {}

    for category, spec in CATEGORIES.items():
        score = sum(
            TITLE_WEIGHT * title_lower.count(word) + text_lower.count(word)
            for word in spec["words"]
        )
        if score:
            scores[category] = score

    if not scores:
        return None, 0

    category, score = max(scores.items(), key=lambda item: item[1])

    if category == "construction":
        mentions = sum(
            title_lower.count(word) + text_lower.count(word)
            for word in ENVIRONMENT_WORDS
        )
        if mentions < MIN_ENVIRONMENT_MENTIONS:
            return None, 0

    if score < MIN_RELEVANCE:
        return None, 0

    return category, score


def title_key(title):
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()[:200]


# ------------------------------------------------------------
# LOCATING
# ------------------------------------------------------------

def place_candidates(title, text):
    """Place names a report mentions, most mentioned first."""
    combined = f"{title}. {text}"
    counts = Counter()

    for name in KNOWN_PLACES:
        hits = len(re.findall(rf"\b{re.escape(name)}\b", combined, flags=re.I))
        if hits:
            counts[name] += 2 * hits

    for name in PLACE_PATTERN.findall(combined):
        if name not in NOT_PLACES and name.split()[0] not in NOT_PLACES:
            counts[name] += 1

    district_names = {name.lower() for name in DISTRICT_DISPLAY_NAMES.values()}
    return [
        name for name, _ in counts.most_common(8)
        if name.lower() not in district_names
    ][:MAX_PLACES_PER_REPORT + 2]


def geocode(name):
    """Coordinates for a place name inside Kashmir, or None. Cached."""
    key = name.lower().strip()[:120]
    cached = get_watch_place(key)

    if cached is not None:
        return cached if cached["found"] else None

    query = urllib.parse.urlencode({
        "q": f"{name}, Jammu and Kashmir",
        "format": "json",
        "limit": 3,
        "countrycodes": "in",
        "viewbox": KASHMIR_VIEWBOX,
        "bounded": 1,
    })

    try:
        results = json.loads(_get(f"{NOMINATIM}?{query}"))
    except Exception:
        return None

    # Accept only a real settlement or natural feature whose own name
    # matches what the report said, not a loose text match.
    match = next(
        (
            result for result in results
            if result.get("type") in PLACE_TYPES
            and key in result.get("display_name", "").split(",")[0].lower()
        ),
        None,
    )

    place = {
        "name_key": key,
        "name": name,
        "found": 1 if match else 0,
        "lat": match["lat"][:10] if match else None,
        "lng": match["lon"][:10] if match else None,
        "kind": match.get("type") if match else None,
        "display_name": match.get("display_name") if match else None,
    }
    save_watch_place(place)
    return place if match else None


_district_polygons = {}

# The city boundary sits inside Srinagar district; reports are filed
# under the district.
NESTED_DISTRICTS = {"sr-c"}


def district_polygons():
    if not _district_polygons:
        import geopandas as gpd

        for path in sorted((Path(PROJECT_ROOT) / "districts-geojson").glob("*.geojson")):
            if path.stem in NESTED_DISTRICTS:
                continue
            frame = gpd.read_file(path)
            if frame.crs is None:
                frame = frame.set_crs("EPSG:4326")
            _district_polygons[path.stem] = frame.to_crs("EPSG:4326").geometry.union_all()

    return _district_polygons


def district_centre(code):
    """Centre of a district polygon, for reports that name only a district."""
    polygon = district_polygons().get(code)
    if polygon is None:
        return None

    point = polygon.representative_point()
    return round(point.y, 5), round(point.x, 5)


def district_of_point(lat, lng):
    from shapely.geometry import Point

    point = Point(lng, lat)
    for code, polygon in district_polygons().items():
        if polygon.contains(point):
            return code
    return None


def district_from_text(title, text):
    """The district a report mentions most, ignoring where it was filed from."""
    body = DATELINE.sub("", text, count=1).lower()
    title = title.lower()
    counts = Counter()

    for alias, code in DISTRICT_ALIASES.items():
        pattern = rf"\b{re.escape(alias)}\b"
        counts[code] += TITLE_WEIGHT * len(re.findall(pattern, title))
        counts[code] += len(re.findall(pattern, body))

    code, count = counts.most_common(1)[0]
    return code if count else None


def locate(title, text):
    """
    Where a report is about. Returns (places, district_code, lat, lng,
    precision). Precision is "place" when a named place was found,
    "district" when only the district is known, and None otherwise.
    """
    places = []
    for name in place_candidates(title, text):
        found = geocode(name)
        if found:
            places.append({
                "name": found["name"],
                "lat": float(found["lat"]),
                "lng": float(found["lng"]),
                "kind": found["kind"],
            })
        if len(places) >= MAX_PLACES_PER_REPORT:
            break

    if places:
        # The place decides the district. A place outside every covered
        # district leaves the district empty.
        district_code = district_of_point(places[0]["lat"], places[0]["lng"])
        return places, district_code, places[0]["lat"], places[0]["lng"], "place"

    district_code = district_from_text(title, text)
    centre = district_centre(district_code) if district_code else None
    if centre:
        return places, district_code, centre[0], centre[1], "district"

    return places, district_code, None, None, None


# ------------------------------------------------------------
# INGESTION
# ------------------------------------------------------------

_ingest_lock = threading.Lock()


def process(report):
    """Classify, locate and store one report. Returns its category, or None."""
    category, relevance = classify(report["title"], report["text"])

    if category is None:
        return None

    places, district_code, lat, lng, precision = locate(report["title"], report["text"])

    if precision is None and not any(
        word in f"{report['title']} {report['text']}".lower() for word in REGION_WORDS
    ):
        return None

    summary = report["summary"] or report["text"]
    excerpt = summary[:EXCERPT_CHARS].rsplit(" ", 1)[0] + ("…" if len(summary) > EXCERPT_CHARS else "")

    stored = add_watch_issue({
        "url": report["url"],
        "title_key": title_key(report["title"]),
        "source": report["source"],
        "title": report["title"],
        "excerpt": excerpt,
        "published_at": report["published_at"],
        "category": category,
        "relevance": relevance,
        "factors_json": json.dumps(CATEGORIES[category]["factors"]),
        "places_json": json.dumps(places),
        "district_code": district_code,
        "lat": None if lat is None else str(lat),
        "lng": None if lng is None else str(lng),
        "location_precision": precision,
        "extractor": "rules",
    })

    return category if stored else None


def ingest(search=True, log=print):
    """
    Read every source once and store new environmental reports.
    Returns counts. Only one ingestion runs at a time.
    """
    if not _ingest_lock.acquire(blocking=False):
        return {"status": "already_running"}

    try:
        init_db()
        reports = []
        errors = []

        for source, spec in SOURCES.items():
            try:
                reports.extend(fetch_feed(source))
            except Exception as exc:
                errors.append(f"{spec['name']} feed: {exc}")

            if search and spec["wordpress"]:
                for term in SEARCH_TERMS:
                    try:
                        reports.extend(search_wordpress(source, term))
                    except Exception as exc:
                        errors.append(f"{spec['name']} search '{term}': {exc}")

        unique = {report["url"]: report for report in reports}
        seen = known_watch_urls(unique)
        fresh = [report for url, report in unique.items() if url not in seen]

        log(f"Watch: {len(unique)} reports read, {len(fresh)} not seen before")

        stored = Counter()
        for report in fresh:
            category = process(report)
            if category:
                stored[category] += 1

        log(f"Watch: {sum(stored.values())} environmental reports stored {dict(stored)}")

        return {
            "status": "done",
            "read": len(unique),
            "new": len(fresh),
            "stored": sum(stored.values()),
            "by_category": dict(stored),
            "errors": errors,
        }
    finally:
        _ingest_lock.release()


def ingest_in_background():
    """Start an ingestion without making the caller wait for it."""
    if _ingest_lock.locked():
        return False

    threading.Thread(target=ingest, name="shuhul-watch", daemon=True).start()
    return True


# ------------------------------------------------------------
# API
# ------------------------------------------------------------

def register_watch_routes(app):
    """
    Register:
      GET  /api/watch/issues?district=&category=&since=
      POST /api/watch/refresh
    """
    from flask import jsonify, request

    @app.get("/api/watch/issues")
    def watch_issues():
        issues = list_watch_issues(
            district=request.args.get("district") or None,
            category=request.args.get("category") or None,
            since=request.args.get("since") or None,
        )

        for issue in issues:
            issue["source_name"] = SOURCES.get(issue["source"], {}).get("name", issue["source"])
            issue["category_label"] = CATEGORIES.get(issue["category"], {}).get("label", issue["category"])
            issue["district"] = DISTRICT_DISPLAY_NAMES.get(issue["district_code"])

        return jsonify({
            "issues": issues,
            "categories": {key: spec["label"] for key, spec in CATEGORIES.items()},
            "sources": {key: spec["name"] for key, spec in SOURCES.items()},
            "last_fetched": latest_watch_fetch(),
            "refreshing": _ingest_lock.locked(),
            "note": (
                "Each item is a claim reported by its source. Shuhul has not "
                "verified it. Locations are taken from place names in the report."
            ),
        })

    @app.post("/api/watch/refresh")
    def watch_refresh():
        started = ingest_in_background()
        return jsonify({"started": started, "refreshing": True}), 202


if __name__ == "__main__":
    print(json.dumps(ingest(), indent=2))
