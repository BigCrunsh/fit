"""Tests for fit/report/headline.py — rule-based headline engine."""

import json

from fit.report.headline import generate_headline


# ════════════════════════════════════════════════════════════════
# Readiness
# ════════════════════════════════════════════════════════════════


class TestHeadlineReadiness:
    # Happy
    def test_high_readiness(self):
        h = generate_headline(readiness=80, acwr=None, phase=None, last_checkin_date=None)
        assert "Ready" in h

    def test_moderate_readiness(self):
        h = generate_headline(readiness=60, acwr=None, phase=None, last_checkin_date=None)
        assert "60" in h
        assert "Moderate" in h or "readiness" in h.lower()

    # Unhappy
    def test_low_readiness_recovery(self):
        h = generate_headline(readiness=40, acwr=None, phase=None, last_checkin_date=None)
        assert "Recovery" in h or "recovery" in h.lower()

    def test_exactly_75(self):
        h = generate_headline(readiness=75, acwr=None, phase=None, last_checkin_date=None)
        assert "Ready" in h

    def test_exactly_50(self):
        h = generate_headline(readiness=50, acwr=None, phase=None, last_checkin_date=None)
        assert "50" in h
        # Should NOT be recovery (>=50 is moderate)
        assert "Recovery day" not in h

    def test_exactly_49(self):
        h = generate_headline(readiness=49, acwr=None, phase=None, last_checkin_date=None)
        assert "Recovery" in h or "recovery" in h.lower()

    def test_zero_readiness(self):
        h = generate_headline(readiness=0, acwr=None, phase=None, last_checkin_date=None)
        assert "Recovery" in h or "recovery" in h.lower()

    def test_none_readiness(self):
        h = generate_headline(readiness=None, acwr=None, phase=None, last_checkin_date=None)
        assert "Sync" in h

    def test_exactly_74(self):
        """74 is moderate, not high."""
        h = generate_headline(readiness=74, acwr=None, phase=None, last_checkin_date=None)
        assert "Moderate" in h or "74" in h
        assert "Ready for training" not in h

    def test_readiness_100(self):
        h = generate_headline(readiness=100, acwr=None, phase=None, last_checkin_date=None)
        assert "Ready" in h


# ════════════════════════════════════════════════════════════════
# ACWR
# ════════════════════════════════════════════════════════════════


class TestHeadlineACWR:
    # Happy
    def test_acwr_safe(self):
        h = generate_headline(readiness=80, acwr=1.0, phase=None, last_checkin_date=None)
        assert "spike" not in h.lower()
        assert "reduce" not in h.lower()
        assert "detraining" not in h.lower()

    def test_acwr_0_7_no_warning(self):
        """0.7 is between 0.6 and 1.3 — no warning."""
        h = generate_headline(readiness=80, acwr=0.7, phase=None, last_checkin_date=None)
        assert "detraining" not in h.lower()
        assert "spike" not in h.lower()

    # Unhappy
    def test_acwr_spike(self):
        h = generate_headline(readiness=80, acwr=1.7, phase=None, last_checkin_date=None)
        assert "spike" in h.lower() or "reduce" in h.lower()

    def test_acwr_approaching(self):
        h = generate_headline(readiness=80, acwr=1.4, phase=None, last_checkin_date=None)
        assert "1.4" in h or "easy" in h.lower() or "approaching" in h.lower()

    def test_acwr_detraining(self):
        h = generate_headline(readiness=80, acwr=0.5, phase=None, last_checkin_date=None)
        assert "detraining" in h.lower() or "0.5" in h

    def test_acwr_exactly_1_3(self):
        """1.3 is borderline — should NOT trigger spike/approaching warning."""
        h = generate_headline(readiness=80, acwr=1.3, phase=None, last_checkin_date=None)
        assert "spike" not in h.lower()
        assert "approaching" not in h.lower()

    def test_acwr_exactly_1_5(self):
        """1.5 is borderline danger — > 1.5 is spike, so 1.5 is still approaching."""
        h = generate_headline(readiness=80, acwr=1.5, phase=None, last_checkin_date=None)
        # 1.5 is > 1.3 but NOT > 1.5, so it should be "approaching"
        assert "approaching" in h.lower() or "easy" in h.lower()
        assert "spike" not in h.lower()

    def test_acwr_exactly_0_6(self):
        """0.6 is borderline detraining — < 0.6 is detraining, so 0.6 is safe."""
        h = generate_headline(readiness=80, acwr=0.6, phase=None, last_checkin_date=None)
        assert "detraining" not in h.lower()

    def test_acwr_exactly_0_59(self):
        h = generate_headline(readiness=80, acwr=0.59, phase=None, last_checkin_date=None)
        assert "detraining" in h.lower()

    def test_acwr_none(self):
        """None ACWR should not produce ACWR-related text."""
        h = generate_headline(readiness=80, acwr=None, phase=None, last_checkin_date=None)
        assert "acwr" not in h.lower()

    def test_acwr_zero(self):
        """ACWR of 0 should trigger detraining warning."""
        h = generate_headline(readiness=80, acwr=0, phase=None, last_checkin_date=None)
        assert "detraining" in h.lower()

    def test_acwr_very_high(self):
        h = generate_headline(readiness=80, acwr=3.0, phase=None, last_checkin_date=None)
        assert "spike" in h.lower() or "reduce" in h.lower()


# ════════════════════════════════════════════════════════════════
# Phase-Aware
# ════════════════════════════════════════════════════════════════


class TestHeadlinePhase:
    # Happy
    def test_phase1_no_quality(self):
        phase = {"name": "Base Building", "targets": json.dumps({"quality_sessions_per_week": 0})}
        h = generate_headline(readiness=80, acwr=1.0, phase=phase, last_checkin_date=None)
        assert "easy" in h.lower() or "no hard" in h.lower()

    def test_phase2_quality_allowed_high_readiness(self):
        phase = {"name": "Volume", "targets": json.dumps({"quality_sessions_per_week": [1, 2]})}
        h = generate_headline(readiness=80, acwr=1.0, phase=phase, last_checkin_date=None)
        assert "quality" in h.lower() or "tempo" in h.lower()

    # Unhappy
    def test_phase_low_readiness_no_quality(self):
        phase = {"name": "Volume", "targets": json.dumps({"quality_sessions_per_week": [1, 2]})}
        h = generate_headline(readiness=55, acwr=1.0, phase=phase, last_checkin_date=None)
        assert "easy" in h.lower() or "save" in h.lower()

    def test_phase_very_low_readiness_no_phase_suggestion(self):
        """Readiness < 50: phase suggestion should NOT appear (condition is readiness >= 50)."""
        phase = {"name": "Volume", "targets": json.dumps({"quality_sessions_per_week": [1, 2]})}
        h = generate_headline(readiness=40, acwr=1.0, phase=phase, last_checkin_date=None)
        assert "Volume" not in h

    def test_phase_none_targets(self):
        """Phase with no targets key."""
        phase = {"name": "Base", "targets": None}
        h = generate_headline(readiness=80, acwr=1.0, phase=phase, last_checkin_date=None)
        # Should not crash; quality_target defaults to 0
        assert "easy" in h.lower() or "no hard" in h.lower()

    def test_phase_empty_targets(self):
        phase = {"name": "Base", "targets": json.dumps({})}
        h = generate_headline(readiness=80, acwr=1.0, phase=phase, last_checkin_date=None)
        assert "easy" in h.lower() or "no hard" in h.lower()

    def test_phase_dict_targets(self):
        """Targets as dict (not JSON string)."""
        phase = {"name": "Volume", "targets": {"quality_sessions_per_week": [1, 2]}}
        h = generate_headline(readiness=80, acwr=1.0, phase=phase, last_checkin_date=None)
        assert "quality" in h.lower() or "tempo" in h.lower()

    def test_no_phase(self):
        """No phase should not mention phase names."""
        h = generate_headline(readiness=80, acwr=1.0, phase=None, last_checkin_date=None)
        assert "Base" not in h and "Volume" not in h

    def test_phase_exactly_readiness_50(self):
        """Readiness=50 should trigger phase suggestion (>= 50)."""
        phase = {"name": "Volume", "targets": json.dumps({"quality_sessions_per_week": [1, 2]})}
        h = generate_headline(readiness=50, acwr=1.0, phase=phase, last_checkin_date=None)
        assert "Volume" in h


# ════════════════════════════════════════════════════════════════
# Checkin Staleness
# ════════════════════════════════════════════════════════════════


class TestHeadlineCheckin:
    # Happy
    def test_fresh_checkin(self):
        h = generate_headline(readiness=80, acwr=None, phase=None,
                              last_checkin_date="2026-04-05", today="2026-04-05")
        # same date should NOT prompt for checkin
        assert "check-in" not in h.lower() or "No check-in" not in h

    # Unhappy
    def test_stale_checkin(self):
        h = generate_headline(readiness=80, acwr=None, phase=None,
                              last_checkin_date="2026-04-03", today="2026-04-05")
        assert "checkin" in h.lower() or "check-in" in h.lower()

    def test_no_checkin_date(self):
        """None last_checkin_date should not crash."""
        h = generate_headline(readiness=80, acwr=None, phase=None,
                              last_checkin_date=None, today="2026-04-05")
        assert len(h) > 0

    def test_no_today(self):
        """None today should not crash."""
        h = generate_headline(readiness=80, acwr=None, phase=None,
                              last_checkin_date="2026-04-03", today=None)
        assert len(h) > 0

    def test_both_none(self):
        h = generate_headline(readiness=80, acwr=None, phase=None,
                              last_checkin_date=None, today=None)
        assert len(h) > 0


# ════════════════════════════════════════════════════════════════
# All-None and Combinations
# ════════════════════════════════════════════════════════════════


class TestHeadlineAllNone:
    def test_all_none(self):
        h = generate_headline(readiness=None, acwr=None, phase=None, last_checkin_date=None)
        assert len(h) > 0
        assert "Sync" in h

    def test_high_readiness_safe_acwr(self):
        h = generate_headline(readiness=80, acwr=1.0, phase=None, last_checkin_date=None)
        assert "Ready" in h
        assert "spike" not in h.lower()

    def test_low_readiness_high_acwr(self):
        h = generate_headline(readiness=35, acwr=1.7, phase=None, last_checkin_date=None)
        assert "Recovery" in h or "recovery" in h.lower()
        assert "spike" in h.lower() or "reduce" in h.lower()

    def test_combined_all_signals(self):
        phase = {"name": "Volume", "targets": json.dumps({"quality_sessions_per_week": [1, 2]})}
        h = generate_headline(readiness=80, acwr=1.7, phase=phase,
                              last_checkin_date="2026-04-01", today="2026-04-05")
        assert "spike" in h.lower() or "reduce" in h.lower()
        assert "checkin" in h.lower() or "check-in" in h.lower()
