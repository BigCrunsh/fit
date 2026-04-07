"""Tests for fit/garmin.py — Garmin API client, fetch functions, retry logic."""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from fit.garmin import (
    fetch_health,
    fetch_activities,
    fetch_spo2,
    _request_with_retry,
)


# ════════════════════════════════════════════════════════════════
# _request_with_retry
# ════════════════════════════════════════════════════════════════


class TestRequestWithRetry:
    """Tests for retry/backoff behavior on various HTTP error codes."""

    def test_success_first_try(self):
        func = MagicMock(return_value={"ok": True})
        result = _request_with_retry(func, max_retries=3, description="test")
        assert result == {"ok": True}
        assert func.call_count == 1

    @patch("fit.garmin.time.sleep")
    def test_429_retries_with_60s_wait(self, mock_sleep):
        func = MagicMock(side_effect=[Exception("429 Too Many Requests"), {"ok": True}])
        result = _request_with_retry(func, max_retries=3, description="test")
        assert result == {"ok": True}
        mock_sleep.assert_called_once_with(60)

    def test_401_raises_runtime_error(self):
        func = MagicMock(side_effect=Exception("401 Unauthorized"))
        with pytest.raises(RuntimeError, match="Garmin auth expired"):
            _request_with_retry(func, max_retries=3, description="test")
        assert func.call_count == 1  # no retries on 401

    @patch("fit.garmin.time.sleep")
    def test_500_retries_with_exponential_backoff(self, mock_sleep):
        func = MagicMock(side_effect=[
            Exception("500 Internal Server Error"),
            Exception("502 Bad Gateway"),
            {"ok": True},
        ])
        result = _request_with_retry(func, max_retries=3, description="test")
        assert result == {"ok": True}
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(1)  # 2^0
        mock_sleep.assert_any_call(2)  # 2^1

    @patch("fit.garmin.time.sleep")
    def test_503_exhausts_retries_returns_none(self, mock_sleep):
        func = MagicMock(side_effect=Exception("503 Service Unavailable"))
        result = _request_with_retry(func, max_retries=3, description="test")
        assert result is None
        assert func.call_count == 3

    def test_unknown_error_retries_then_raises(self):
        func = MagicMock(side_effect=ValueError("unexpected"))
        with pytest.raises(ValueError, match="unexpected"):
            _request_with_retry(func, max_retries=3, description="test")
        assert func.call_count == 3


# ════════════════════════════════════════════════════════════════
# fetch_health
# ════════════════════════════════════════════════════════════════


class TestFetchHealth:
    """Tests for fetch_health dict mapping from API response."""

    def _mock_api(self):
        api = MagicMock()
        api.get_stats.return_value = {
            "totalSteps": 8500,
            "totalDistanceMeters": 6200.0,
            "totalKilocalories": 2100,
            "activeKilocalories": 800,
            "restingHeartRate": 55,
            "maxHeartRate": 142,
            "minHeartRate": 48,
            "averageStressLevel": 32,
            "maxStressLevel": 72,
            "bodyBatteryChargedValue": 95,
            "bodyBatteryDrainedValue": 20,
        }
        api.get_sleep_data.return_value = {
            "dailySleepDTO": {
                "deepSleepSeconds": 3600,
                "lightSleepSeconds": 14400,
                "remSleepSeconds": 5400,
                "awakeSleepSeconds": 1800,
            }
        }
        api.get_hrv_data.return_value = {
            "hrvSummary": {"weeklyAvg": 45, "lastNightAvg": 42, "status": "BALANCED"}
        }
        api.get_training_readiness.return_value = {"score": 78, "level": "PRIME"}
        api.get_respiration_data.return_value = {"avgWakingRespirationValue": 16.5}
        return api

    def test_maps_stats_correctly(self):
        api = self._mock_api()
        results = fetch_health(api, date(2025, 1, 1), date(2025, 1, 1))
        assert len(results) == 1
        h = results[0]
        assert h["date"] == "2025-01-01"
        assert h["total_steps"] == 8500
        assert h["resting_heart_rate"] == 55
        assert h["body_battery_high"] == 95
        assert h["body_battery_low"] == 20

    def test_maps_sleep_correctly(self):
        api = self._mock_api()
        results = fetch_health(api, date(2025, 1, 1), date(2025, 1, 1))
        h = results[0]
        assert h["sleep_duration_hours"] == round((3600 + 14400 + 5400) / 3600, 2)
        assert h["deep_sleep_hours"] == 1.0
        assert h["rem_sleep_hours"] == 1.5

    def test_maps_hrv_correctly(self):
        api = self._mock_api()
        results = fetch_health(api, date(2025, 1, 1), date(2025, 1, 1))
        h = results[0]
        assert h["hrv_weekly_avg"] == 45
        assert h["hrv_last_night"] == 42
        assert h["hrv_status"] == "BALANCED"

    def test_maps_readiness_correctly(self):
        api = self._mock_api()
        results = fetch_health(api, date(2025, 1, 1), date(2025, 1, 1))
        h = results[0]
        assert h["training_readiness"] == 78
        assert h["readiness_level"] == "PRIME"

    def test_handles_training_readiness_as_list(self):
        api = self._mock_api()
        api.get_training_readiness.return_value = [{"score": 65, "level": "HIGH"}]
        results = fetch_health(api, date(2025, 1, 1), date(2025, 1, 1))
        h = results[0]
        assert h["training_readiness"] == 65

    def test_multi_day_range(self):
        api = self._mock_api()
        results = fetch_health(api, date(2025, 1, 1), date(2025, 1, 3))
        assert len(results) == 3
        assert results[0]["date"] == "2025-01-01"
        assert results[2]["date"] == "2025-01-03"

    def test_returns_empty_on_no_data(self):
        api = MagicMock()
        api.get_stats.return_value = None
        api.get_sleep_data.return_value = None
        api.get_hrv_data.return_value = None
        api.get_training_readiness.return_value = None
        api.get_respiration_data.return_value = None
        results = fetch_health(api, date(2025, 1, 1), date(2025, 1, 1))
        assert len(results) == 0

    def test_partial_data_still_returns(self):
        api = MagicMock()
        api.get_stats.return_value = {"totalSteps": 5000}
        api.get_sleep_data.side_effect = Exception("sleep API down")
        api.get_hrv_data.return_value = None
        api.get_training_readiness.return_value = None
        api.get_respiration_data.return_value = None
        results = fetch_health(api, date(2025, 1, 1), date(2025, 1, 1))
        assert len(results) == 1
        assert results[0]["total_steps"] == 5000


# ════════════════════════════════════════════════════════════════
# fetch_activities
# ════════════════════════════════════════════════════════════════


class TestFetchActivities:
    """Tests for fetch_activities normalization: distance m->km, duration s->min."""

    def _mock_api(self):
        api = MagicMock()
        api.get_activities_by_date.return_value = [
            {
                "activityId": 12345,
                "startTimeLocal": "2025-01-15 07:30:00",
                "activityType": {"typeKey": "running"},
                "distance": 10000.0,  # meters
                "duration": 3000.0,   # seconds
                "averageHR": 145,
                "maxHR": 168,
                "averageRunningCadenceInStepsPerMinute": 172,
                "elevationGain": 120.5,
                "calories": 650,
                "vO2MaxValue": 48.5,
                "aerobicTrainingEffect": 3.2,
                "activityTrainingLoad": 210,
                "avgStrideLength": 115,  # cm
                "averageSpeed": 3.33,
                "startLatitude": 52.52,
                "startLongitude": 13.405,
                "activityName": "Morning Run",
            }
        ]
        return api

    def test_distance_converted_m_to_km(self):
        api = self._mock_api()
        results = fetch_activities(api, date(2025, 1, 15), date(2025, 1, 15))
        assert len(results) == 1
        assert results[0]["distance_km"] == 10.0

    def test_duration_converted_s_to_min(self):
        api = self._mock_api()
        results = fetch_activities(api, date(2025, 1, 15), date(2025, 1, 15))
        assert results[0]["duration_min"] == 50.0

    def test_pace_computed_correctly(self):
        api = self._mock_api()
        results = fetch_activities(api, date(2025, 1, 15), date(2025, 1, 15))
        # 50 min / 10 km * 60 = 300 sec/km
        assert results[0]["pace_sec_per_km"] == 300

    def test_type_extraction(self):
        api = self._mock_api()
        results = fetch_activities(api, date(2025, 1, 15), date(2025, 1, 15))
        assert results[0]["type"] == "running"

    def test_type_extraction_string_fallback(self):
        api = MagicMock()
        api.get_activities_by_date.return_value = [
            {"activityId": 999, "activityType": "cycling", "startTimeLocal": "2025-01-15 08:00:00",
             "distance": 5000, "duration": 600}
        ]
        results = fetch_activities(api, date(2025, 1, 15), date(2025, 1, 15))
        assert results[0]["type"] == "cycling"

    def test_stride_length_cm_to_m(self):
        api = self._mock_api()
        results = fetch_activities(api, date(2025, 1, 15), date(2025, 1, 15))
        assert results[0]["avg_stride_m"] == 1.15

    def test_start_hour_extracted(self):
        api = self._mock_api()
        results = fetch_activities(api, date(2025, 1, 15), date(2025, 1, 15))
        assert results[0]["start_hour"] == 7

    def test_deduplication(self):
        api = MagicMock()
        api.get_activities_by_date.return_value = [
            {"activityId": 100, "startTimeLocal": "2025-01-15 08:00:00",
             "activityType": {"typeKey": "running"}, "distance": 5000, "duration": 1200},
            {"activityId": 100, "startTimeLocal": "2025-01-15 08:00:00",
             "activityType": {"typeKey": "running"}, "distance": 5000, "duration": 1200},
        ]
        results = fetch_activities(api, date(2025, 1, 15), date(2025, 1, 15))
        assert len(results) == 1

    def test_zero_distance_no_pace(self):
        api = MagicMock()
        api.get_activities_by_date.return_value = [
            {"activityId": 200, "startTimeLocal": "2025-01-15 10:00:00",
             "activityType": {"typeKey": "fitness_equipment"}, "distance": 0, "duration": 1800}
        ]
        results = fetch_activities(api, date(2025, 1, 15), date(2025, 1, 15))
        assert results[0]["pace_sec_per_km"] is None
        assert results[0]["distance_km"] is None

    def test_subtype_auto_detected(self):
        api = MagicMock()
        api.get_activities_by_date.return_value = [
            {"activityId": 300, "startTimeLocal": "2025-01-15 12:00:00",
             "activityType": {"typeKey": "running"}, "distance": 2000, "duration": 600,
             "activityName": "Move IQ Walking", "autoCalcCalories": False}
        ]
        results = fetch_activities(api, date(2025, 1, 15), date(2025, 1, 15))
        assert results[0]["subtype"] == "auto_detected"


# ════════════════════════════════════════════════════════════════
# fetch_spo2
# ════════════════════════════════════════════════════════════════


class TestFetchSpo2:
    """Tests for fetch_spo2 dict mapping."""

    def test_maps_average_spo2(self):
        api = MagicMock()
        api.get_spo2_data.return_value = {"averageSpO2": 97}
        results = fetch_spo2(api, date(2025, 1, 1), date(2025, 1, 1))
        assert results == {"2025-01-01": 97}

    def test_none_when_no_data(self):
        api = MagicMock()
        api.get_spo2_data.return_value = None
        results = fetch_spo2(api, date(2025, 1, 1), date(2025, 1, 1))
        assert results == {"2025-01-01": None}

    def test_none_on_api_error(self):
        api = MagicMock()
        api.get_spo2_data.side_effect = Exception("API error")
        results = fetch_spo2(api, date(2025, 1, 1), date(2025, 1, 1))
        assert results == {"2025-01-01": None}

    def test_multi_day_range(self):
        api = MagicMock()
        api.get_spo2_data.side_effect = [
            {"averageSpO2": 97},
            {"averageSpO2": 96},
            None,
        ]
        results = fetch_spo2(api, date(2025, 1, 1), date(2025, 1, 3))
        assert results["2025-01-01"] == 97
        assert results["2025-01-02"] == 96
        assert results["2025-01-03"] is None
