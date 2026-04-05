"""Weather data from Open-Meteo API (free, no key required)."""

import logging
from datetime import date

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://archive-api.open-meteo.com/v1/archive"


def fetch_daily_weather(d: date, lat: float, lon: float) -> dict | None:
    """Fetch daily weather for a single date at a location.

    Returns dict with temp_c, temp_max_c, temp_min_c, humidity_pct,
    wind_speed_kmh, precipitation_mm, conditions. Or None on failure.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": d.isoformat(),
        "end_date": d.isoformat(),
        "daily": "temperature_2m_mean,temperature_2m_max,temperature_2m_min,"
                 "relative_humidity_2m_mean,wind_speed_10m_max,precipitation_sum,"
                 "weather_code",
        "timezone": "auto",
    }

    try:
        resp = requests.get(BASE_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning("Weather fetch failed for %s: %s", d, e)
        return None

    daily = data.get("daily", {})
    if not daily or not daily.get("time"):
        return None

    return {
        "date": d.isoformat(),
        "temp_c": _first(daily.get("temperature_2m_mean")),
        "temp_max_c": _first(daily.get("temperature_2m_max")),
        "temp_min_c": _first(daily.get("temperature_2m_min")),
        "humidity_pct": _first(daily.get("relative_humidity_2m_mean")),
        "wind_speed_kmh": _first(daily.get("wind_speed_10m_max")),
        "precipitation_mm": _first(daily.get("precipitation_sum")),
        "conditions": _weather_code_to_text(_first(daily.get("weather_code"))),
    }


def fetch_hourly_weather(d: date, hour: int, lat: float, lon: float) -> dict | None:
    """Fetch hourly weather for a specific date and hour.

    Returns dict with temp_c and humidity_pct for the specified hour. Or None.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": d.isoformat(),
        "end_date": d.isoformat(),
        "hourly": "temperature_2m,relative_humidity_2m",
        "timezone": "auto",
    }

    try:
        resp = requests.get(BASE_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning("Hourly weather fetch failed for %s hour %d: %s", d, hour, e)
        return None

    hourly = data.get("hourly", {})
    temps = hourly.get("temperature_2m", [])
    humidity = hourly.get("relative_humidity_2m", [])

    if hour < len(temps):
        return {
            "temp_at_start_c": temps[hour],
            "humidity_at_start_pct": humidity[hour] if hour < len(humidity) else None,
        }
    return None


def _first(lst: list | None) -> float | None:
    """Get the first element of a list, or None."""
    if lst and len(lst) > 0:
        return lst[0]
    return None


def _weather_code_to_text(code: int | None) -> str | None:
    """Convert WMO weather code to human-readable text."""
    if code is None:
        return None
    codes = {
        0: "Clear", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
        45: "Fog", 48: "Rime fog",
        51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
        61: "Light rain", 63: "Rain", 65: "Heavy rain",
        71: "Light snow", 73: "Snow", 75: "Heavy snow",
        80: "Light showers", 81: "Showers", 82: "Heavy showers",
        95: "Thunderstorm", 96: "Thunderstorm + hail",
    }
    return codes.get(code, f"WMO {code}")
