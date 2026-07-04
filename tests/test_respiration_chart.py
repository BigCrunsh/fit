"""Respiration chart on the Readiness tab (wellness-early-warning).

Sleep series primary, waking muted, baseline ± delta band from the same
wellness_snapshot the alert rules read. No data → no chart (no empty box).
"""

import json
from datetime import date, timedelta

from fit.report.sections.charts import _all_charts


def _day(offset):
    return (date.today() - timedelta(days=offset)).isoformat()


def _fill(db, start_offset, days, **cols):
    for i in range(days):
        keys = ["date"] + list(cols.keys())
        vals = [_day(start_offset + i)] + list(cols.values())
        db.execute(
            f"INSERT INTO daily_health ({','.join(keys)}) VALUES ({','.join('?' * len(vals))})",
            vals,
        )
    db.commit()


def _respiration_chart(db):
    charts = _all_charts(db)
    entry = next((c for c in charts if c["id"] == "chart-respiration"), None)
    return json.loads(entry["config"]) if entry else None


class TestRespirationChart:
    def test_omitted_without_data(self, db):
        assert _respiration_chart(db) is None

    def test_rendered_with_both_series_and_band(self, db):
        _fill(db, 0, 30, avg_sleep_respiration=15.0, avg_respiration=14.0)
        cfg = _respiration_chart(db)
        assert cfg is not None
        labels = [d["label"] for d in cfg["data"]["datasets"]]
        assert any("sleep" in label.lower() for label in labels)
        assert any("waking" in label.lower() for label in labels)
        anns = cfg["options"]["plugins"]["annotation"]["annotations"]
        assert "baseline_band" in anns
        band = anns["baseline_band"]
        assert band["yMin"] == 15.0 and band["yMax"] == 17.0  # baseline ± delta (2.0)

    def test_band_omitted_when_baseline_undefined(self, db):
        _fill(db, 0, 5, avg_sleep_respiration=15.0)  # 5 obs < 14 → no baseline
        cfg = _respiration_chart(db)
        assert cfg is not None  # series still shown
        anns = cfg.get("options", {}).get("plugins", {}).get("annotation", {}).get("annotations", {})
        assert "baseline_band" not in anns

    def test_waking_only_data_still_renders(self, db):
        _fill(db, 0, 30, avg_respiration=14.0)
        cfg = _respiration_chart(db)
        assert cfg is not None
        labels = [d["label"] for d in cfg["data"]["datasets"]]
        assert any("waking" in label.lower() for label in labels)
        assert not any("sleep" in label.lower() for label in labels)

    def test_band_uses_40plus_hex_opacity(self, db):
        # CLAUDE.md: annotation bands use 40+ hex opacity, never 0c/10/18
        _fill(db, 0, 30, avg_sleep_respiration=15.0)
        cfg = _respiration_chart(db)
        band = cfg["options"]["plugins"]["annotation"]["annotations"]["baseline_band"]
        bg = band["backgroundColor"]
        assert bg.startswith("#") and len(bg) == 9
        assert int(bg[7:9], 16) >= int("40", 16)
