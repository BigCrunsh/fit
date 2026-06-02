"""Suggest → confirm governance: anchors change only on the human's accept.

evaluate_suggestions surfaces a metric whose policy suggestion differs from the
confirmed value; accept writes a confirmed anchor; reject records a ledger entry
that suppresses re-raising the same value until it moves.
"""

from datetime import date, timedelta

from fit.calibration import (
    evaluate_suggestions, accept_suggestion, reject_suggestion,
    load_review, get_active_calibration,
)


def _ins(db, value, method, days_ago, active=0, confidence="medium"):
    db.execute(
        "INSERT INTO calibration (metric, value, method, confidence, date, active, flags) "
        "VALUES ('vdot', ?, ?, ?, ?, ?, '[]')",
        (value, method, confidence, (date.today() - timedelta(days=days_ago)).isoformat(), active),
    )
    db.commit()


def _seed_diverging(db):
    # Confirmed 41 (out of the 180d window) + a fresh 38.9 race observation in-window.
    _ins(db, 41.0, "confirmed", days_ago=220, active=1, confidence="high")
    _ins(db, 38.9, "race_estimate", days_ago=30, confidence="low")


class TestEvaluate:
    def test_differing_suggestion_is_surfaced(self, db):
        _seed_diverging(db)
        pend = evaluate_suggestions(db, review={})
        assert [p["metric"] for p in pend] == ["vdot"]
        assert pend[0]["value"] == 38.9 and pend[0]["active"] == 41.0

    def test_no_suggestion_when_within_threshold(self, db):
        _ins(db, 41.0, "confirmed", days_ago=200, active=1, confidence="high")
        _ins(db, 40.5, "race_estimate", days_ago=20)   # within differs 1.0 of 41
        assert evaluate_suggestions(db, review={}) == []

    def test_dismissed_value_is_suppressed(self, db):
        _seed_diverging(db)
        review = {"vdot": {"state": "dismissed", "value": 38.9}}
        assert evaluate_suggestions(db, review=review) == []

    def test_dismissed_then_moved_is_re_raised(self, db):
        _seed_diverging(db)
        review = {"vdot": {"state": "dismissed", "value": 35.0}}  # moved > differs from 38.9
        assert len(evaluate_suggestions(db, review=review)) == 1


class TestAcceptReject:
    def test_accept_writes_confirmed_anchor(self, db, tmp_path):
        _seed_diverging(db)
        p = str(tmp_path / "review.json")
        v = accept_suggestion(db, "vdot", path=p)
        assert v == 38.9
        active = get_active_calibration(db, "vdot")
        assert active["value"] == 38.9 and active["method"] == "confirmed"
        # Now active == suggestion → nothing left to surface.
        assert evaluate_suggestions(db, review=load_review(p)) == []

    def test_reject_records_ledger_and_suppresses(self, db, tmp_path):
        _seed_diverging(db)
        p = str(tmp_path / "review.json")
        reject_suggestion(db, "vdot", path=p)
        review = load_review(p)
        assert review["vdot"]["state"] == "dismissed" and review["vdot"]["value"] == 38.9
        assert evaluate_suggestions(db, review=review) == []
        # Active is unchanged (still the confirmed 41).
        assert get_active_calibration(db, "vdot")["value"] == 41.0
