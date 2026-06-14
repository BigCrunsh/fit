"""Dashboard information-architecture structure guards (dashboard-information-architecture,
stage 2, group 6).

These render the real template and assert the IA contract that the hub's story logic relies
on — relocated detail lives under its owning tab (not the Overview), each detail tab opens
with a one-line lead, every hub `→` link resolves to an anchor that exists (no dead links),
and the deep-link plumbing (`showTab` 3-arg + reveal-all-then-restore + hash routing) is
present. They are deliberately data-light: they assert the always-present structure, so they
stay green on a thin DB and fail loudly if a relocation or an anchor regresses.

The hub's *story* logic (verdict/limiter/status/precedence/graceful-empty) is unit-tested in
test_overview_hub.py; this file guards the template wiring those values render into.
"""

import tempfile
from pathlib import Path

from fit.report.generator import generate_dashboard
from fit.report.sections.cards import _HUB_LEVER

# Source-order of the tab <div>s in the template (DOM order, not the triage button order).
_TAB_ORDER = ["overview", "profile", "training", "readiness", "coach"]

# Every anchor the hub can emit a `→` link to. The _HUB_LEVER ones are imported (so a lever
# anchor change is caught); the card + verdict anchors are string literals in `_overview_hub`
# and are pinned here as the contract. If the hub starts linking somewhere new, add it here
# AND add the target id to the template — that's the no-dead-link guarantee.
_HUB_LINK_ANCHORS = (
    {anchor for (_tab, anchor, _lever) in _HUB_LEVER.values()}
    | {"train-objectives", "readiness-acwr", "prof-vo2max", "coach-insights"}  # card anchors
    | {"prof-prediction"}  # verdict anchor
)


def _render(db):
    with tempfile.TemporaryDirectory() as tmpdir:
        out = Path(tmpdir) / "dashboard.html"
        generate_dashboard(db, out)
        return out.read_text()


def _tab_slice(html, tab):
    """The HTML between this tab's <div> and the next tab's (or end)."""
    i = html.find(f'id="tab-{tab}"')
    assert i != -1, f"tab-{tab} not found"
    nxt = _TAB_ORDER[_TAB_ORDER.index(tab) + 1] if tab != _TAB_ORDER[-1] else None
    j = html.find(f'id="tab-{nxt}"') if nxt else len(html)
    return html[i:j]


class TestNoDeadLinks:
    """6.5 — every hub `→` link target anchor exists in the rendered template."""

    def test_all_hub_link_anchors_exist(self, db):
        html = _render(db)
        for anchor in _HUB_LINK_ANCHORS:
            assert f'id="{anchor}"' in html, f"dead hub link: no id=\"{anchor}\" in template"

    def test_each_anchor_is_unique(self, db):
        # A duplicate id would make scroll targeting ambiguous.
        html = _render(db)
        for anchor in _HUB_LINK_ANCHORS:
            assert html.count(f'id="{anchor}"') == 1, f"id=\"{anchor}\" is not unique"


class TestRelocatedDetailLivesInOwningTab:
    """6.4 — relocated detail is under its owning tab and gone from the Overview."""

    def test_objectives_anchor_under_training_not_overview(self, db):
        html = _render(db)
        assert 'id="train-objectives"' in _tab_slice(html, "training")
        assert 'id="train-objectives"' not in _tab_slice(html, "overview")

    def test_acwr_anchor_under_readiness(self, db):
        html = _render(db)
        assert 'id="readiness-acwr"' in _tab_slice(html, "readiness")

    def test_coach_insights_anchor_under_coach(self, db):
        html = _render(db)
        assert 'id="coach-insights"' in _tab_slice(html, "coach")

    def test_checkpoints_moved_off_overview_to_coach(self, db):
        html = _render(db)
        assert 'id="checkpoints-table"' not in _tab_slice(html, "overview")
        # Rendered only when prediction_trend exists; never on the Overview.
        if 'id="checkpoints-table"' in html:
            assert 'id="checkpoints-table"' in _tab_slice(html, "coach")

    def test_physiology_card_not_on_overview(self, db):
        # Relocated to Profile — must not linger on the Overview (it renders on Profile when
        # the four anchors are available; here we only assert it left the Overview).
        html = _render(db)
        assert 'class="physiology-card"' not in _tab_slice(html, "overview")

    def test_overview_carries_the_synthesis_hub(self, db):
        # The Overview keeps the synthesis hub (verdict/limiter/strip) or its empty prompt.
        html = _render(db)
        ov = _tab_slice(html, "overview")
        assert 'class="hub"' in ov or 'class="hub-empty"' in ov


class TestDetailTabsLeadWithTheAnswer:
    """6.4 — each detail tab opens with a one-line lead. Profile and Coach leads are always
    present (they have an else branch); Training/Readiness leads render when their supporting
    data exists (graceful-absent otherwise)."""

    def test_profile_leads_with_an_answer(self, db):
        html = _render(db)
        prof = _tab_slice(html, "profile")
        assert 'class="tab-lead"' in prof
        # Lead comes before the first detail section (conclusion-first, not a card pile).
        assert prof.find('class="tab-lead"') < prof.find('id="prof-today"')

    def test_coach_leads_with_an_answer(self, db):
        html = _render(db)
        coach = _tab_slice(html, "coach")
        assert 'class="tab-lead"' in coach
        # The lead carries the always-present coach-insights anchor at the top of the tab.
        assert 'id="coach-insights"' in coach
        assert coach.find('id="coach-insights"') < coach.find("Coaching Notes") \
            if "Coaching Notes" in coach else True


class TestDeepLinkPlumbing:
    """6.5 — showTab is the 3-arg target+hash path, charts still init via reveal-all, and a
    hash routes on load."""

    def test_showtab_takes_a_section_arg(self, db):
        assert "function showTab(id, btn, section)" in _render(db)

    def test_reveal_all_then_restore_pass_present(self, db):
        html = _render(db)
        assert "t.style.display = 'block'" in html  # reveal for init (no 0×0)
        assert "t.style.display = ''" in html        # restore after init

    def test_hash_routing_on_load(self, db):
        html = _render(db)
        assert "function routeFromHash" in html
        assert "DOMContentLoaded" in html and "routeFromHash" in html
