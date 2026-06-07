"""Feature extraction for the marathon-durability model (no PyMC).

Covers effort selection, incoming chronic load (the shared ACWR primitive, evaluated
strictly BEFORE each effort), the x/c/h/logt covariates, goal-adaptive D_REF, LTHR from
the calibration anchor, and the graceful-failure cases the caller turns into "degrade to
the anchor headline".
"""

import math
from datetime import date, timedelta

import pytest

from fit.marathon.features import extract_efforts, MARATHON_KM
from fit.training_load import CHRONIC_WINDOW_DAYS


def _d(days_ago):
    return (date.today() - timedelta(days=days_ago)).isoformat()


def _set_lthr(db, value=170.0):
    db.execute(
        "INSERT INTO calibration (metric, value, method, confidence, date, active) "
        "VALUES ('lthr', ?, 'manual', 'high', ?, 1)",
        (value, _d(1)),
    )
    db.commit()


def _set_max_hr(db, value=195.0):
    db.execute(
        "INSERT INTO calibration (metric, value, method, confidence, date, active) "
        "VALUES ('max_hr', ?, 'manual', 'high', ?, 1)",
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
        _act(db, "load1", 40, run_type="easy", distance_km=8, duration_min=45,
             avg_hr=140, training_load=80)
        _act(db, "race10", 30, run_type="race", distance_km=10.0, duration_min=50,
             avg_hr=175, training_load=120)
        _act(db, "raceHM", 10, run_type="race", distance_km=21.1, duration_min=110,
             avg_hr=168, training_load=200)

        ds = extract_efforts(db)
        eff = ds.efforts
        assert set(eff["id"]) == {"race10", "raceHM"}

        hm = eff[eff["id"] == "raceHM"].iloc[0]
        # No target race set → D_REF falls back to the marathon.
        assert ds.goal == pytest.approx(MARATHON_KM)
        assert hm["x"] == pytest.approx(math.log(21.1) - math.log(MARATHON_KM))
        assert hm["h"] == pytest.approx((168 - 170.0) / 5.0)
        assert hm["logt"] == pytest.approx(math.log(110))
        assert ds.d_max == pytest.approx(21.1)
        assert ds.lthr == pytest.approx(170.0)
        assert ds.max_hr is None         # no MaxHR anchor set → cap is a no-op downstream

    def test_max_hr_from_anchor(self, db):
        _set_lthr(db, 170.0)
        _set_max_hr(db, 192.0)
        _act(db, "load", 40, run_type="easy", distance_km=8, duration_min=45,
             avg_hr=140, training_load=80)
        _act(db, "race", 30, run_type="race", distance_km=10.0, duration_min=50, avg_hr=175)
        ds = extract_efforts(db)
        assert ds.max_hr == pytest.approx(192.0)   # MaxHR anchor flows into the dataset

    def test_long_run_qualifies_regardless_of_class(self, db):
        _set_lthr(db, 170.0)
        _act(db, "load", 40, run_type="easy", distance_km=8, duration_min=45,
             avg_hr=140, training_load=80)
        # an EASY 18 km long run — not a race, not a Hard tempo, but a durability anchor
        _act(db, "longrun", 20, run_type="long", distance_km=18.0, duration_min=110,
             avg_hr=150, effort_class="Easy", training_load=200)
        ds = extract_efforts(db)
        eff = ds.efforts
        assert "longrun" in set(eff["id"])              # admitted by the >=15km rule
        lr = eff[eff["id"] == "longrun"].iloc[0]
        assert lr["h"] == pytest.approx((150 - 170.0) / 5.0)   # sub-maximal HR kept via h, not dropped

    def test_chronic_is_trailing_mean_strictly_before(self, db):
        _set_lthr(db)
        # one prior load 7 days before the effort; a big SAME-DAY load must be excluded
        # (incoming fitness). chronic = sum(in-window loads) / window.
        _act(db, "prior", 37, run_type="easy", distance_km=8, duration_min=45,
             avg_hr=140, training_load=100)
        _act(db, "race", 30, run_type="race", distance_km=10.0, duration_min=50,
             avg_hr=175, training_load=999)  # 999 same-day → excluded
        ds = extract_efforts(db)
        eff = ds.efforts
        assert eff.iloc[0]["chronic"] == pytest.approx(100 / CHRONIC_WINDOW_DAYS, rel=1e-6)

    def test_goal_adaptive_recenters_x(self, db, monkeypatch):
        _set_lthr(db)
        _act(db, "load", 40, run_type="easy", distance_km=8, duration_min=45,
             avg_hr=140, training_load=80)
        _act(db, "race10", 20, run_type="race", distance_km=10.0, duration_min=50, avg_hr=175)
        # Target a half-marathon → x re-centres on 21.1, not the marathon.
        monkeypatch.setattr("fit.goals.get_target_race", lambda conn: {"distance_km": 21.1})
        ds = extract_efforts(db)
        eff = ds.efforts
        assert ds.goal == pytest.approx(21.1)
        assert eff.iloc[0]["x"] == pytest.approx(math.log(10.0) - math.log(21.1))


class TestExtractEffortsUnhappy:
    def test_excludes_intervals_easy_and_easy_tempo(self, db):
        _set_lthr(db)
        _act(db, "load", 40, run_type="easy", distance_km=8, duration_min=45,
             avg_hr=140, training_load=80)
        _act(db, "race", 30, run_type="race", distance_km=10, duration_min=50, avg_hr=175)
        _act(db, "interval", 25, run_type="interval", distance_km=12, duration_min=55,
             avg_hr=178, effort_class="Very Hard")
        _act(db, "easy", 20, run_type="easy", distance_km=10, duration_min=60, avg_hr=140)
        _act(db, "tempo_easy", 15, run_type="tempo", distance_km=10, duration_min=50,
             avg_hr=150, effort_class="Easy")
        ds = extract_efforts(db)
        eff = ds.efforts
        assert set(eff["id"]) == {"race"}

    def test_long_interval_excluded_but_long_run_kept(self, db):
        _set_lthr(db)
        _act(db, "load", 40, run_type="easy", distance_km=8, duration_min=45,
             avg_hr=140, training_load=80)
        _act(db, "longrun", 25, run_type="long", distance_km=16.0, duration_min=95,
             avg_hr=150, training_load=180)
        # a 16 km interval session — long, but its time spans recoveries → not a continuous effort
        _act(db, "longint", 20, run_type="interval", distance_km=16.0, duration_min=80,
             avg_hr=160, effort_class="Very Hard", training_load=200)
        ds = extract_efforts(db)
        ids = set(ds.efforts["id"])
        assert "longrun" in ids and "longint" not in ids

    def test_short_moderate_tempo_still_excluded(self, db):
        _set_lthr(db)
        _act(db, "load", 40, run_type="easy", distance_km=8, duration_min=45,
             avg_hr=140, training_load=80)
        _act(db, "race", 30, run_type="race", distance_km=10, duration_min=50, avg_hr=175)
        # a <15km Moderate tempo still needs Hard/Very-Hard to qualify
        _act(db, "modtempo", 20, run_type="tempo", distance_km=10, duration_min=50,
             avg_hr=155, effort_class="Moderate")
        ds = extract_efforts(db)
        ids = set(ds.efforts["id"])
        assert "race" in ids and "modtempo" not in ids

    def test_drops_effort_without_prior_history(self, db):
        _set_lthr(db)
        _act(db, "early", 60, run_type="race", distance_km=10, duration_min=50, avg_hr=175)
        _act(db, "load", 30, run_type="easy", distance_km=8, duration_min=45,
             avg_hr=140, training_load=90)
        _act(db, "later", 10, run_type="race", distance_km=10, duration_min=50, avg_hr=175)
        ds = extract_efforts(db)
        eff = ds.efforts
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
        _act(db, "race_no_hr", 30, run_type="race", distance_km=10, duration_min=50, avg_hr=0)
        with pytest.raises(ValueError, match="no qualifying efforts"):
            extract_efforts(db)
