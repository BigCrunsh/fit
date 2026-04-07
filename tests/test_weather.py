"""Tests for fit/weather.py — Open-Meteo API client, daily/hourly weather, code mapping."""

from datetime import date
from unittest.mock import patch, MagicMock


from fit.weather import (
    fetch_daily_weather,
    fetch_hourly_weather,
    _weather_code_to_text,
    _first,
)


# ════════════════════════════════════════════════════════════════
# fetch_daily_weather
# ════════════════════════════════════════════════════════════════


class TestFetchDailyWeather:
    """Tests for fetch_daily_weather parsing of Open-Meteo response."""

    def _mock_response(self):
        return {
            "daily": {
                "time": ["2025-01-15"],
                "temperature_2m_mean": [5.2],
                "temperature_2m_max": [8.1],
                "temperature_2m_min": [1.3],
                "relative_humidity_2m_mean": [72],
                "wind_speed_10m_max": [18.5],
                "precipitation_sum": [2.4],
                "weather_code": [61],
            }
        }

    @patch("fit.weather.requests.get")
    def test_parses_response_correctly(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = self._mock_response()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = fetch_daily_weather(date(2025, 1, 15), 52.52, 13.405)
        assert result is not None
        assert result["date"] == "2025-01-15"
        assert result["temp_c"] == 5.2
        assert result["temp_max_c"] == 8.1
        assert result["temp_min_c"] == 1.3
        assert result["humidity_pct"] == 72
        assert result["wind_speed_kmh"] == 18.5
        assert result["precipitation_mm"] == 2.4
        assert result["conditions"] == "Light rain"

    @patch("fit.weather.requests.get")
    def test_returns_none_on_empty_daily(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"daily": {}}
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = fetch_daily_weather(date(2025, 1, 15), 52.52, 13.405)
        assert result is None

    @patch("fit.weather.requests.get")
    def test_returns_none_on_api_error(self, mock_get):
        import requests as req
        mock_get.side_effect = req.exceptions.ConnectionError("Connection timeout")

        result = fetch_daily_weather(date(2025, 1, 15), 52.52, 13.405)
        assert result is None

    @patch("fit.weather.requests.get")
    def test_returns_none_on_http_error(self, mock_get):
        import requests as req
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.raise_for_status.side_effect = req.exceptions.HTTPError("400 Bad Request")
        mock_get.return_value = mock_resp

        result = fetch_daily_weather(date(2025, 1, 15), 52.52, 13.405)
        assert result is None

    @patch("fit.weather.requests.get")
    def test_returns_none_when_no_time_key(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "daily": {"temperature_2m_mean": [5.2]}
        }
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = fetch_daily_weather(date(2025, 1, 15), 52.52, 13.405)
        assert result is None


# ════════════════════════════════════════════════════════════════
# fetch_hourly_weather
# ════════════════════════════════════════════════════════════════


class TestFetchHourlyWeather:
    """Tests for fetch_hourly_weather returning correct hour data."""

    @patch("fit.weather.requests.get")
    def test_returns_correct_hour(self, mock_get):
        temps = [i + 2.0 for i in range(24)]
        humidity = [50 + i for i in range(24)]
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "hourly": {
                "temperature_2m": temps,
                "relative_humidity_2m": humidity,
            }
        }
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = fetch_hourly_weather(date(2025, 1, 15), 8, 52.52, 13.405)
        assert result is not None
        assert result["temp_at_start_c"] == 10.0  # 8 + 2.0
        assert result["humidity_at_start_pct"] == 58  # 50 + 8

    @patch("fit.weather.requests.get")
    def test_returns_none_when_hour_out_of_range(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "hourly": {
                "temperature_2m": [5.0, 6.0],  # only 2 hours
                "relative_humidity_2m": [50, 55],
            }
        }
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = fetch_hourly_weather(date(2025, 1, 15), 10, 52.52, 13.405)
        assert result is None

    @patch("fit.weather.requests.get")
    def test_returns_none_on_api_error(self, mock_get):
        import requests as req
        mock_get.side_effect = req.exceptions.ConnectionError("timeout")
        result = fetch_hourly_weather(date(2025, 1, 15), 8, 52.52, 13.405)
        assert result is None

    @patch("fit.weather.requests.get")
    def test_humidity_none_when_missing(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "hourly": {
                "temperature_2m": [5.0] * 24,
                "relative_humidity_2m": [],  # empty
            }
        }
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = fetch_hourly_weather(date(2025, 1, 15), 8, 52.52, 13.405)
        assert result is not None
        assert result["temp_at_start_c"] == 5.0
        assert result["humidity_at_start_pct"] is None


# ════════════════════════════════════════════════════════════════
# _weather_code_to_text
# ════════════════════════════════════════════════════════════════


class TestWeatherCodeToText:
    """Tests for WMO weather code mapping."""

    def test_clear(self):
        assert _weather_code_to_text(0) == "Clear"

    def test_partly_cloudy(self):
        assert _weather_code_to_text(2) == "Partly cloudy"

    def test_light_rain(self):
        assert _weather_code_to_text(61) == "Light rain"

    def test_heavy_snow(self):
        assert _weather_code_to_text(75) == "Heavy snow"

    def test_thunderstorm(self):
        assert _weather_code_to_text(95) == "Thunderstorm"

    def test_unknown_code_returns_wmo(self):
        assert _weather_code_to_text(99) == "WMO 99"

    def test_none_returns_none(self):
        assert _weather_code_to_text(None) is None


# ════════════════════════════════════════════════════════════════
# _first helper
# ════════════════════════════════════════════════════════════════


class TestFirst:
    def test_returns_first_element(self):
        assert _first([42, 43]) == 42

    def test_returns_none_for_empty(self):
        assert _first([]) is None

    def test_returns_none_for_none(self):
        assert _first(None) is None
