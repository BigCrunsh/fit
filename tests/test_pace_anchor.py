"""Regression: Pace Zones must anchor to the performance VDOT, not Garmin VO2max.

The dashboard's VDOT Trend section tells the athlete to trust the *anchor*
VDOT (a race/training effort) over Garmin's wrist-HR VO2max, which runs
optimistic. The Pace Zones table previously derived Daniels paces from the
Garmin VO2max calibration — so the dashboard said "trust 36" while handing out
paces built from "49", which would prescribe paces far too fast. These tests
pin the corrected behaviour: anchor when one exists, fall back to the
calibration only when there's no qualifying effort.
"""

from datetime import date, timedelta

from fit.calibration import add_calibration
from fit.analysis import compute_daniels_paces
from fit.report.sections.cards import _pace_zones


def _ins_run(db, aid, days_ago, distance_km, duration_min, avg_hr):
    d = (date.today() - timedelta(days=days_ago)).isoformat()
    db.execute(
        "INSERT INTO activities (id, date, type, distance_km, duration_min, avg_hr) "
        "VALUES (?, ?, 'running', ?, ?, ?)",
        (aid, d, distance_km, duration_min, avg_hr),
    )
    return d


class TestPaceZonesAnchor:
    def test_uses_anchor_vdot_not_garmin_calibration(self, db):
        """With a qualifying effort present, paces come from the anchor VDOT —
        NOT the (higher, optimistic) Garmin VO2max calibration."""
        add_calibration(db, "lthr", 172, "manual", "high", date.today())
        # Garmin VO2max calibration sits high — the WRONG number to pace off.
        add_calibration(db, "vo2max", 49, "garmin", "medium", date.today())
        # A qualifying 10K at avg HR ≥ LTHR → an anchor near VDOT ~45.
        _ins_run(db, "hard10k", 20, 10.0, 45.0, 178)
        db.commit()

        from fit.fitness import get_fitness_anchors
        anchor_vdot = sorted(get_fitness_anchors(db, days=365),
                             key=lambda a: a["date"], reverse=True)[0]["vdot"]
        assert anchor_vdot < 49, "test setup: anchor must differ from Garmin 49"

        pz = _pace_zones(db)
        assert pz["available"] is True
        assert pz["vdot_source"] == "anchor"
        assert pz["vo2max"] == anchor_vdot
        # Paces must match the anchor VDOT, not the Garmin calibration.
        expected = compute_daniels_paces(vo2max=anchor_vdot)
        garmin = compute_daniels_paces(vo2max=49)
        assert pz["rows"][0]["range"] != _range(garmin, "E"), \
            "paces must not be derived from Garmin VO2max"
        assert pz["rows"][0]["range"] == _range(expected, "E")

    def test_falls_back_to_calibration_without_anchor(self, db):
        """No qualifying effort → fall back to the VO2max calibration so the
        table still renders, and the source is flagged 'garmin'."""
        add_calibration(db, "lthr", 172, "manual", "high", date.today())
        add_calibration(db, "vo2max", 48, "garmin", "medium", date.today())
        db.commit()  # no activities → no anchor

        pz = _pace_zones(db)
        assert pz["available"] is True
        assert pz["vdot_source"] == "garmin"
        assert pz["vo2max"] == 48

    def test_unavailable_when_no_anchor_and_no_calibration(self, db):
        """Neither an effort nor a calibration → unavailable with a prompt."""
        add_calibration(db, "lthr", 172, "manual", "high", date.today())
        db.commit()
        pz = _pace_zones(db)
        assert pz["available"] is False
        assert "LTHR" in pz["missing"] or "effort" in pz["missing"]


def _range(paces, key):
    """Mirror cards._row's range formatting for comparison."""
    def fmt(s):
        m, sec = divmod(int(round(s)), 60)
        return f"{m}:{sec:02d}"
    lo, hi = paces[key]["lo"], paces[key]["hi"]
    return fmt(lo) if lo == hi else f"{fmt(lo)}-{fmt(hi)}"
