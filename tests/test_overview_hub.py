"""Overview synthesis hub logic (dashboard-information-architecture, stage 2).

The pure decision helpers — per-domain status vs a defensible reference, and the single-
limiter pick (worst status, tie by gap) — are unit-tested here. `_overview_hub(conn)` wiring
is covered lightly (graceful on an empty DB); the values it reuses are tested with their own
builders elsewhere.
"""

from fit.report.sections.cards import (
    _hub_acwr_status, _hub_pick_limiter, _hub_vdot_status, _hub_volume_status, _overview_hub,
)


class TestVdotStatus:
    # the one new cutoff: ≤1 on-track · 1–3 watch · >3 off-track
    def test_cutoffs(self):
        assert _hub_vdot_status(50, 50)[0] == "safe"      # exactly on target
        assert _hub_vdot_status(49, 50)[0] == "safe"      # 1 under (≤1)
        assert _hub_vdot_status(48, 50)[0] == "caution"   # 2 under (1–3)
        assert _hub_vdot_status(47, 50)[0] == "caution"   # 3 under (boundary)
        assert _hub_vdot_status(46, 50)[0] == "danger"    # 4 under (>3)

    def test_above_target_is_safe(self):
        assert _hub_vdot_status(52, 50)[0] == "safe"

    def test_neutral_without_a_reference(self):
        assert _hub_vdot_status(None, 50)[0] == "neutral"
        assert _hub_vdot_status(48, None)[0] == "neutral"


class TestVolumeStatus:
    # Reference is the phase [min, max] range (not a fixed % of a single target).
    def test_in_range_is_safe(self):
        assert _hub_volume_status(50, 40, 60)[0] == "safe"
        assert _hub_volume_status(40, 40, 60)[0] == "safe"     # at min (boundary)
        assert _hub_volume_status(60, 40, 60)[0] == "safe"     # at max (boundary)

    def test_outside_range(self):
        assert _hub_volume_status(35, 40, 60)[0] == "caution"  # 5 under min (< 20 width)
        assert _hub_volume_status(10, 40, 60)[0] == "danger"   # 30 under min (> 20 width)
        assert _hub_volume_status(70, 40, 60)[0] == "caution"  # 10 over max (< 20 width)

    def test_neutral_without_range(self):
        assert _hub_volume_status(40, None, None)[0] == "neutral"
        assert _hub_volume_status(None, 40, 60)[0] == "neutral"

    def test_gap_fraction(self):
        status, gap = _hub_volume_status(10, 40, 60)           # 30 under min(40), > width 20
        assert status == "danger" and round(gap, 2) == 0.75


class TestAcwrStatus:
    SAFE, DANGER_HI = [0.8, 1.3], 1.5   # the config bands, passed in

    def test_bands(self):
        assert _hub_acwr_status(1.0, self.SAFE, self.DANGER_HI)[0] == "safe"     # in band
        assert _hub_acwr_status(1.4, self.SAFE, self.DANGER_HI)[0] == "caution"  # 1.3–1.5
        assert _hub_acwr_status(1.6, self.SAFE, self.DANGER_HI)[0] == "danger"   # > danger_hi
        assert _hub_acwr_status(0.7, self.SAFE, self.DANGER_HI)[0] == "caution"  # below band, above derived lo
        assert _hub_acwr_status(0.5, self.SAFE, self.DANGER_HI)[0] == "danger"   # below derived lo

    def test_low_danger_bound_is_derived_from_config(self):
        # danger_lo = lo - (danger_hi - hi) = 0.8 - 0.2 = 0.6 — derived, not hardcoded
        assert _hub_acwr_status(0.61, self.SAFE, self.DANGER_HI)[0] == "caution"
        assert _hub_acwr_status(0.59, self.SAFE, self.DANGER_HI)[0] == "danger"

    def test_neutral_when_missing(self):
        assert _hub_acwr_status(None, self.SAFE, self.DANGER_HI)[0] == "neutral"
        assert _hub_acwr_status(1.0, None, self.DANGER_HI)[0] == "neutral"


class TestPickLimiter:
    def _cards(self, **status):
        gaps = {"Fitness": 0.30, "Recovery": 0.20, "Physiology": 0.10}
        return [{"label": L, "status": status.get(L, "safe"), "gap": gaps.get(L, 0.0)}
                for L in ("Fitness", "Recovery", "Physiology", "Coach")]

    def test_none_when_all_safe(self):
        assert _hub_pick_limiter(self._cards()) is None

    def test_danger_beats_caution_regardless_of_gap(self):
        # Physiology danger (gap 0.10) outranks Fitness caution (gap 0.30) — severity first
        lim = _hub_pick_limiter(self._cards(Fitness="caution", Physiology="danger"))
        assert lim["label"] == "Physiology"

    def test_tie_broken_by_larger_gap(self):
        lim = _hub_pick_limiter(self._cards(Fitness="caution", Recovery="caution"))
        assert lim["label"] == "Fitness"   # same severity → larger gap (0.30 > 0.20)

    def test_coach_is_never_the_limiter(self):
        cards = self._cards(Recovery="caution")
        cards[3]["status"] = "danger"      # Coach can't be a limiter (narrative, no target)
        assert _hub_pick_limiter(cards)["label"] == "Recovery"

    def test_limiter_carries_lever_and_link(self):
        lim = _hub_pick_limiter(self._cards(Physiology="danger"))
        assert lim["tab"] == "profile" and lim["lever"] and lim["status"] == "danger"


class TestOverviewHubIntegration:
    def test_graceful_on_empty_db(self, db):
        # No goal, no data → None or a neutral/empty payload — never an exception
        res = _overview_hub(db)
        assert res is None or res.get("empty") is True or "cards" in res
