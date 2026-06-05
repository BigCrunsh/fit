"""Feature extraction for the marathon-durability model (no PyMC).

Covers effort selection, incoming CTL/ATL computed strictly BEFORE each effort day,
the x/c/h/logt covariates, LTHR sourced from the calibration anchor, and the
graceful-failure cases the caller turns into "degrade to the anchor headline".
"""

import math
from datetime import date, timedelta

import numpy as np
import pytest

from fit.marathon.features import extract_efforts, TAU_CTL, TAU_ATL, D_REF


def _d(days_ago):
    return (date.today() - timedelta(days=days_ago)).isoformat()


def _set_lthr(db, value=170.0):
    db.execute(
        "INSERT INTO calibration (metric, value, method, confidence, date, active) "
        "VALUES ('lthr', ?, 'manual', 'high', ?, 1)",
        (value, _d(1)),
    )
    db.commit()


def _act(db, aid, days_ago, *, run_type, distance_km, duration_min, avg_hr,
         training_load=None, effort_class=None, type_="running"):
    db.execute(
        "INSERT INTO activities (id, date, type, run_type, distance_km, duration_min, "
        "avg_hr, training_load, effort_class) VALUES (?,?,?,?,?,?,?,?,?)",
        (aid, _d(days_ago), type_, run_type, distance_km, duration_min, avg_hr,
         training_load, effort_class),
    )
    db.commit()


class TestExtractEffortsHappy:
    def test_covariates_and_attrs(self, db):
        _set_lthr(db, 170.0)
        # prior load history so CTL > 0
        _act(db, "load1", 40, run_type="easy", distance_km=8, duration_min=45,
             avg_hr=140, training_load=80)
        _act(db, "race10", 30, run_type="race", distance_km=10.0, duration_min=50,
             avg_hr=175, training_load=120)
        _act(db, "raceHM", 10, run_type="race", distance_km=21.1, duration_min=110,
             avg_hr=168, training_load=200)

        eff = extract_efforts(db)
        assert set(eff["id"]) == {"race10", "raceHM"}

        hm = eff[eff["id"] == "raceHM"].iloc[0]
        assert hm["x"] == pytest.approx(math.log(21.1) - math.log(D_REF))
        assert hm["h"] == pytest.approx((168 - 170.0) / 5.0)
        assert hm["logt"] == pytest.approx(math.log(110))
        assert eff.attrs["d_max"] == pytest.approx(21.1)
        assert eff.attrs["lthr"] == pytest.approx(170.0)

    def test_ctl_atl_strictly_before(self, db):
        _set_lthr(db)
        # one prior load 7 days before the effort, plus a big SAME-DAY load that must
        # be excluded (incoming fitness, not inflated by the effort's own load).
        _act(db, "prior", 37, run_type="easy", distance_km=8, duration_min=45,
             avg_hr=140, training_load=100)
        _act(db, "race", 30, run_type="race", distance_km=10.0, duration_min=50,
             avg_hr=175, training_load=999)  # 999 is same-day → must NOT count

        eff = extract_efforts(db)
        row = eff.iloc[0]
        expected_ctl = 100 * math.exp(-7 / TAU_CTL) / TAU_CTL
        expected_atl = 100 * math.exp(-7 / TAU_ATL) / TAU_ATL
        assert row["ctl"] == pytest.approx(expected_ctl, rel=1e-6)
        assert row["atl"] == pytest.approx(expected_atl, rel=1e-6)


class TestExtractEffortsUnhappy:
    def test_excludes_intervals_easy_and_easy_tempo(self, db):
        _set_lthr(db)
        _act(db, "load", 40, run_type="easy", distance_km=8, duration_min=45,
             avg_hr=140, training_load=80)
        _act(db, "race", 30, run_type="race", distance_km=10, duration_min=50, avg_hr=175)
        _act(db, "interval", 25, run_type="interval", distance_km=12, duration_min=55,
             avg_hr=178, effort_class="Very Hard")           # intervals excluded
        _act(db, "easy", 20, run_type="easy", distance_km=10, duration_min=60, avg_hr=140)
        _act(db, "tempo_easy", 15, run_type="tempo", distance_km=10, duration_min=50,
             avg_hr=150, effort_class="Easy")                # tempo but not Hard/Very Hard
        eff = extract_efforts(db)
        assert set(eff["id"]) == {"race"}

    def test_drops_effort_without_prior_history(self, db):
        _set_lthr(db)
        # "early" race has no load before it → CTL=0 → dropped; "later" has history.
        _act(db, "early", 60, run_type="race", distance_km=10, duration_min=50, avg_hr=175)
        _act(db, "load", 30, run_type="easy", distance_km=8, duration_min=45,
             avg_hr=140, training_load=90)
        _act(db, "later", 10, run_type="race", distance_km=10, duration_min=50, avg_hr=175)
        eff = extract_efforts(db)
        assert set(eff["id"]) == {"later"}

    def test_raises_without_lthr_anchor(self, db):
        _act(db, "load", 40, run_type="easy", distance_km=8, duration_min=45,
             avg_hr=140, training_load=80)
        _act(db, "race", 30, run_type="race", distance_km=10, duration_min=50, avg_hr=175)
        with pytest.raises(ValueError, match="LTHR"):
            extract_efforts(db)

    def test_raises_without_qualifying_efforts(self, db):
        _set_lthr(db)
        _act(db, "easy", 20, run_type="easy", distance_km=10, duration_min=60, avg_hr=140)
        with pytest.raises(ValueError, match="no qualifying efforts"):
            extract_efforts(db)

    def test_raises_when_all_efforts_lack_history(self, db):
        _set_lthr(db)
        _act(db, "race", 30, run_type="race", distance_km=10, duration_min=50, avg_hr=175)
        with pytest.raises(ValueError, match="prior training history"):
            extract_efforts(db)

    def test_excludes_effort_with_missing_hr(self, db):
        _set_lthr(db)
        _act(db, "load", 40, run_type="easy", distance_km=8, duration_min=45,
             avg_hr=140, training_load=80)
        _act(db, "race_no_hr", 30, run_type="race", distance_km=10, duration_min=50,
             avg_hr=0)                                        # avg_hr=0 excluded by SQL
        with pytest.raises(ValueError, match="no qualifying efforts"):
            extract_efforts(db)
