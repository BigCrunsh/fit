"""Pace Zones derive from the single standardized VDOT anchor.

The dashboard's VDOT Trend, Pace Zones, and forecast must all read the same
VDOT via get_calibration_anchor — the human-confirmed sticky value, or the
windowed-max policy estimate from race observations when none is confirmed.
Garmin's optimistic wrist-HR VO2max is reference-only and must never drive
training paces (it would prescribe paces far too fast).
"""

from datetime import date, timedelta

from fit.analysis import compute_daniels_paces
from fit.report.sections.cards import _pace_zones


def _ins_vdot(db, value, method, days_ago, active=0, confidence="medium"):
    db.execute(
        "INSERT INTO calibration (metric, value, method, confidence, date, active, flags) "
        "VALUES ('vdot', ?, ?, ?, ?, ?, '[]')",
        (value, method, confidence, (date.today() - timedelta(days=days_ago)).isoformat(), active),
    )
    db.commit()


def _range(paces, key):
    def fmt(s):
        m, sec = divmod(int(round(s)), 60)
        return f"{m}:{sec:02d}"
    lo, hi = paces[key]["lo"], paces[key]["hi"]
    return fmt(lo) if lo == hi else f"{fmt(lo)}-{fmt(hi)}"


class TestPaceZonesAnchor:
    def test_uses_confirmed_anchor_not_garmin(self, db):
        """A confirmed VDOT drives paces; the Garmin VO2max estimate is ignored."""
        _ins_vdot(db, 38.9, "manual", days_ago=10, active=1, confidence="high")
        # Garmin wrist-HR estimate sits high — must NOT be used for paces.
        db.execute("INSERT INTO calibration (metric, value, method, confidence, date, active, flags) "
                   "VALUES ('vdot', 49, 'garmin_estimate', 'medium', ?, 0, '[]')",
                   ((date.today() - timedelta(days=5)).isoformat(),))
        db.commit()

        pz = _pace_zones(db)
        assert pz["available"] is True
        assert pz["vo2max"] == 38.9
        assert pz["vdot_source"] == "anchor"
        assert pz["rows"][0]["range"] == _range(compute_daniels_paces(vo2max=38.9), "E")
        assert pz["rows"][0]["range"] != _range(compute_daniels_paces(vo2max=49), "E")

    def test_bootstrap_uses_windowed_max_when_unconfirmed(self, db):
        """No confirmed row → paces use the windowed-max of race observations."""
        _ins_vdot(db, 35.5, "race_estimate", days_ago=70, confidence="low")
        _ins_vdot(db, 38.9, "race_estimate", days_ago=30, confidence="low")
        pz = _pace_zones(db)
        assert pz["available"] is True
        assert pz["vo2max"] == 38.9          # the max, not the trail 35.5

    def test_unavailable_without_any_vdot_observation(self, db):
        """Only a Garmin estimate (reference-only) → no paces, prompt to race."""
        db.execute("INSERT INTO calibration (metric, value, method, confidence, date, active, flags) "
                   "VALUES ('vdot', 49, 'garmin_estimate', 'medium', ?, 1, '[]')",
                   (date.today().isoformat(),))
        db.commit()
        pz = _pace_zones(db)
        assert pz["available"] is False
        assert "LTHR" in pz["missing"] or "effort" in pz["missing"]
