"""
Shuhul air and temperature context.

Current conditions and history for a district, from Open-Meteo:

    weather   ERA5 reanalysis and forecast   about 10 to 25 km grid
    air       CAMS global air quality model  about 40 km grid, from Aug 2022

Both are far coarser than the map layers. One grid cell covers a whole
city, so these numbers describe the district as a whole and cannot tell
one neighbourhood from another. Air quality here is a model estimate,
not a reading from a monitor on the ground.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import json
import time
import urllib.parse
import urllib.request

from ..config import OUTPUT_ROOT, PROCESSED_ROOT, PROJECT_ROOT

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
AIR_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

TIMEZONE = "Asia/Kolkata"
HISTORY_START_YEAR = 2017
AIR_HISTORY_DAYS = 365

CURRENT_MAX_AGE_SECONDS = 60 * 60
HISTORY_MAX_AGE_SECONDS = 24 * 60 * 60

# India's national standard for PM2.5 averaged over 24 hours, in µg/m³.
PM25_DAILY_STANDARD = 60.0

# Central Pollution Control Board bands for 24-hour PM2.5, in µg/m³.
PM25_BANDS = [
    (30, "Good"),
    (60, "Satisfactory"),
    (90, "Moderate"),
    (120, "Poor"),
    (250, "Very poor"),
    (float("inf"), "Severe"),
]

USER_AGENT = "Shuhul/0.1 environmental planning research (github.com/hanaanllone/shuhul)"

# ESA WorldCover class for built-up land.
BUILT_UP_CLASS = 50


class ClimateUnavailable(Exception):
    """The district is unknown or the data source could not be reached."""


# ------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------

def _get(url, params):
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(f"{url}?{query}", headers={"User-Agent": USER_AGENT})

    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def _cached(name, max_age, build):
    """Return a saved result while it is fresh, otherwise rebuild and save it."""
    path = Path(OUTPUT_ROOT) / "climate" / f"{name}.json"

    if path.exists() and time.time() - path.stat().st_mtime < max_age:
        return json.loads(path.read_text(encoding="utf-8"))

    try:
        result = build()
    except Exception as exc:
        # A stale answer is better than none when the source is down.
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        raise ClimateUnavailable(str(exc)) from exc

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result), encoding="utf-8")
    return result


def district_point(district):
    """
    The point the district's weather and air are read at, as (latitude,
    longitude): the middle of its built-up land, which is where people
    are. A district's geometric centre can sit on a mountainside and
    read several degrees colder than its towns.
    """
    import geopandas as gpd

    path = Path(PROJECT_ROOT) / "districts-geojson" / f"{district}.geojson"
    if not path.exists():
        raise ClimateUnavailable(f"Unknown district: {district}")

    built_up = _built_up_centre(district)
    if built_up is not None:
        return built_up

    frame = gpd.read_file(path)
    if frame.crs is None:
        frame = frame.set_crs("EPSG:4326")

    point = frame.to_crs("EPSG:4326").geometry.union_all().representative_point()
    return round(point.y, 4), round(point.x, 4)


def _built_up_centre(district):
    """Median position of built-up land-cover cells, or None without that layer."""
    import numpy as np
    import rasterio
    from pyproj import Transformer

    path = Path(PROCESSED_ROOT) / district / "landcover.tif"
    if not path.exists():
        return None

    with rasterio.open(path) as src:
        # A coarse read is plenty for finding a centre.
        step = max(1, max(src.width, src.height) // 800)
        cells = src.read(1, out_shape=(src.height // step, src.width // step))
        rows, cols = np.nonzero(cells == BUILT_UP_CLASS)

        if rows.size == 0:
            return None

        x, y = src.transform * (
            (float(np.median(cols)) + 0.5) * step,
            (float(np.median(rows)) + 0.5) * step,
        )
        lng, lat = Transformer.from_crs(src.crs, "EPSG:4326", always_xy=True).transform(x, y)

    return round(lat, 4), round(lng, 4)


def pm25_band(value):
    if value is None:
        return None
    return next(label for limit, label in PM25_BANDS if value <= limit)


def _mean(values):
    values = [value for value in values if value is not None]
    return round(sum(values) / len(values), 1) if values else None


# ------------------------------------------------------------
# WEATHER
# ------------------------------------------------------------

def _temperature_history(lat, lng):
    """Monthly normals of daily maximum and minimum since HISTORY_START_YEAR."""
    today = date.today()
    data = _get(ARCHIVE_URL, {
        "latitude": lat,
        "longitude": lng,
        "start_date": f"{HISTORY_START_YEAR}-01-01",
        "end_date": (today - timedelta(days=7)).isoformat(),
        "daily": "temperature_2m_max,temperature_2m_min",
        "timezone": TIMEZONE,
    })["daily"]

    by_month = defaultdict(lambda: {"max": [], "min": []})
    by_year_month = defaultdict(list)
    hottest = None

    for day, high, low in zip(data["time"], data["temperature_2m_max"], data["temperature_2m_min"]):
        if high is None or low is None:
            continue

        month = int(day[5:7])
        by_month[month]["max"].append(high)
        by_month[month]["min"].append(low)
        by_year_month[(int(day[:4]), month)].append(high)

        if hottest is None or high > hottest["temperature_c"]:
            hottest = {"date": day, "temperature_c": high}

    normals = {
        str(month): {
            "mean_max_c": _mean(values["max"]),
            "mean_min_c": _mean(values["min"]),
        }
        for month, values in sorted(by_month.items())
    }

    # Mean daily maximum of each July, to show how summers have moved.
    july = {
        str(year): _mean(values)
        for (year, month), values in sorted(by_year_month.items())
        if month == 7
    }

    return {
        "period": f"{HISTORY_START_YEAR} to {today.year}",
        "monthly_normals": normals,
        "july_mean_max_c": july,
        "hottest_day": hottest,
    }


def _temperature_now(lat, lng):
    data = _get(FORECAST_URL, {
        "latitude": lat,
        "longitude": lng,
        "current": "temperature_2m,relative_humidity_2m,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min",
        "forecast_days": 1,
        "timezone": TIMEZONE,
    })

    return {
        "time": data["current"]["time"],
        "temperature_c": data["current"]["temperature_2m"],
        "humidity_pct": data["current"]["relative_humidity_2m"],
        "wind_kmh": data["current"]["wind_speed_10m"],
        "today_max_c": data["daily"]["temperature_2m_max"][0],
        "today_min_c": data["daily"]["temperature_2m_min"][0],
    }


# ------------------------------------------------------------
# AIR
# ------------------------------------------------------------

def _air_now(lat, lng):
    current = _get(AIR_URL, {
        "latitude": lat,
        "longitude": lng,
        "current": "pm2_5,pm10,nitrogen_dioxide,ozone,sulphur_dioxide,carbon_monoxide",
        "timezone": TIMEZONE,
    })["current"]

    return {
        "time": current["time"],
        "pm2_5": current["pm2_5"],
        "pm10": current["pm10"],
        "no2": current["nitrogen_dioxide"],
        "o3": current["ozone"],
        "so2": current["sulphur_dioxide"],
        "co": current["carbon_monoxide"],
        "pm2_5_band": pm25_band(current["pm2_5"]),
        "unit": "µg/m³",
    }


def _air_history(lat, lng):
    """Daily mean PM2.5 over the past year, by month, and days over the standard."""
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=AIR_HISTORY_DAYS - 1)

    hourly = _get(AIR_URL, {
        "latitude": lat,
        "longitude": lng,
        "hourly": "pm2_5",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "timezone": TIMEZONE,
    })["hourly"]

    by_day = defaultdict(list)
    for stamp, value in zip(hourly["time"], hourly["pm2_5"]):
        if value is not None:
            by_day[stamp[:10]].append(value)

    daily = {day: sum(values) / len(values) for day, values in by_day.items()}

    by_month = defaultdict(list)
    for day, value in daily.items():
        by_month[day[:7]].append(value)

    return {
        "period": f"{start.isoformat()} to {end.isoformat()}",
        "days_with_data": len(daily),
        "days_over_standard": sum(1 for value in daily.values() if value > PM25_DAILY_STANDARD),
        "standard_pm2_5": PM25_DAILY_STANDARD,
        "annual_mean_pm2_5": _mean(daily.values()),
        "monthly_mean_pm2_5": {
            month: {
                "pm2_5": _mean(values),
                "band": pm25_band(_mean(values)),
                "days_over_standard": sum(1 for value in values if value > PM25_DAILY_STANDARD),
            }
            for month, values in sorted(by_month.items())
        },
    }


# ------------------------------------------------------------
# PUBLIC
# ------------------------------------------------------------

def _part(name, max_age, build):
    """One piece of the answer, or None when its source cannot be reached."""
    try:
        return _cached(name, max_age, build)
    except ClimateUnavailable:
        return None


def district_climate(district):
    """
    Weather and air for a district. The four pieces come from different
    endpoints and are fetched separately, so one being down leaves the
    others in place; a missing piece is reported in "unavailable".
    """
    lat, lng = district_point(district)

    parts = {
        "weather_now": _part(
            f"{district}_weather_now", CURRENT_MAX_AGE_SECONDS,
            lambda: _temperature_now(lat, lng),
        ),
        "weather_history": _part(
            f"{district}_weather_history", HISTORY_MAX_AGE_SECONDS,
            lambda: _temperature_history(lat, lng),
        ),
        "air_now": _part(
            f"{district}_air_now", CURRENT_MAX_AGE_SECONDS,
            lambda: _air_now(lat, lng),
        ),
        "air_history": _part(
            f"{district}_air_history", HISTORY_MAX_AGE_SECONDS,
            lambda: _air_history(lat, lng),
        ),
    }

    if all(value is None for value in parts.values()):
        raise ClimateUnavailable("no source could be reached")

    weather = {**(parts["weather_now"] or {}), **(parts["weather_history"] or {})}
    month = str(datetime.now(timezone.utc).astimezone().month)
    normal = weather.get("monthly_normals", {}).get(month, {}).get("mean_max_c")

    if normal is not None and weather.get("today_max_c") is not None:
        weather["normal_max_for_month_c"] = normal
        weather["today_vs_normal_c"] = round(weather["today_max_c"] - normal, 1)

    return {
        "district": district,
        "point": {"lat": lat, "lng": lng},
        "weather": weather or None,
        "air": {**(parts["air_now"] or {}), **(parts["air_history"] or {})} or None,
        "unavailable": [name for name, value in parts.items() if value is None],
        "method": {
            "weather_source": "Open-Meteo: ERA5 reanalysis for history, forecast model for today",
            "air_source": "Open-Meteo: CAMS global air quality model",
            "resolution": (
                "One value for the whole district. The weather grid is about 10 to 25 km "
                "and the air quality grid about 40 km."
            ),
            "air_note": (
                "A model estimate, not a ground monitor reading. "
                "It cannot tell one neighbourhood from another."
            ),
            "bands": "PM2.5 bands follow the Central Pollution Control Board 24-hour scale.",
            "confidence": "Low for air quality, medium for temperature",
        },
    }


def register_climate_routes(app):
    """Register GET /api/climate/<district>."""
    from flask import jsonify

    @app.get("/api/climate/<district>")
    def climate(district):
        try:
            return jsonify(district_climate(district))
        except ClimateUnavailable as exc:
            return jsonify({"error": f"Air and temperature data unavailable: {exc}"}), 503
