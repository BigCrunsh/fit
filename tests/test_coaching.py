"""Coaching core: context assembly, notes writer, and the claude-CLI runner.

Runner tests mock the subprocess (no real claude call) and assert the fail-closed contract:
every failure path raises CoachError and leaves reports/coaching.json untouched.
"""

import json
import subprocess

import pytest

from fit.coaching.save import save_coaching_notes
from fit.coaching import runner as R

VALID = '[{"type": "warning", "title": "Ease the long run", "body": "Sundays 18km ran at Z3 (HR 161) above the 153 Z2 ceiling; cap the first 15km easier."}]'


def _envelope(text, is_error=False, subtype="success"):
    return json.dumps({"type": "result", "subtype": subtype, "is_error": is_error, "result": text})


def _fake_run(returncode=0, stdout="", stderr=""):
    def run(cmd, capture_output=True, text=True, timeout=None):
        return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)
    return run


# ── context assembly (SSOT) ──

class TestAssembleContext:
    def test_assembles_structured_context(self, db):
        from fit.coaching.context import assemble_coaching_context
        # minimal: a run + a health row so several sections populate
        db.execute("INSERT INTO activities (id,date,type,name,distance_km,duration_min,avg_hr,hr_zone,run_type,pace_sec_per_km) "
                   "VALUES ('r1', date('now'), 'running', 'Easy', 8, 45, 140, 'Z2', 'easy', 337)")
        db.commit()
        out = assemble_coaching_context(db)
        assert out.startswith("Coaching Context:")
        assert "Profile:" in out                       # _ctx_profile ran
        assert "\n  " in out                            # sections are indented


# ── notes writer (moved verbatim from the MCP) ──

class TestSaveCoachingNotes:
    def test_valid_writes_and_archives(self, tmp_path):
        res = save_coaching_notes(VALID, reports_dir=tmp_path)
        assert "Saved 1" in res
        data = json.loads((tmp_path / "coaching.json").read_text())
        assert data["insights"][0]["type"] == "warning" and data["report_date"]
        # second save archives the first to coaching_history.json
        save_coaching_notes(VALID, reports_dir=tmp_path)
        hist = json.loads((tmp_path / "coaching_history.json").read_text())
        assert len(hist) == 1

    def test_short_body_rejected_no_write(self, tmp_path):
        res = save_coaching_notes('[{"type":"info","title":"x","body":"too short"}]', reports_dir=tmp_path)
        assert res.startswith("Error:")
        assert not (tmp_path / "coaching.json").exists()   # nothing written

    def test_missing_type_rejected(self, tmp_path):
        res = save_coaching_notes('[{"title":"x","body":"a body long enough to pass the length check"}]', reports_dir=tmp_path)
        assert res.startswith("Error:") and not (tmp_path / "coaching.json").exists()

    def test_invalid_json_rejected(self, tmp_path):
        assert save_coaching_notes("not json", reports_dir=tmp_path).startswith("Error:")
        assert not (tmp_path / "coaching.json").exists()


# ── runner (mocked claude subprocess) — fail closed everywhere ──

class TestRunCoach:
    def _patch(self, monkeypatch):
        monkeypatch.setattr(R, "assemble_coaching_context", lambda conn: "CTX")  # no DB needed

    def test_happy_saves(self, tmp_path, monkeypatch):
        self._patch(monkeypatch)
        monkeypatch.setattr(R.subprocess, "run", _fake_run(0, _envelope(VALID)))
        res = R.run_coach(None, reports_dir=tmp_path, claude_bin="claude-dummy")
        assert res["saved"] is True
        assert (tmp_path / "coaching.json").exists()

    def test_no_save_validates_but_writes_nothing(self, tmp_path, monkeypatch):
        self._patch(monkeypatch)
        monkeypatch.setattr(R.subprocess, "run", _fake_run(0, _envelope(VALID)))
        res = R.run_coach(None, reports_dir=tmp_path, save=False, claude_bin="claude-dummy")
        assert res["saved"] is False and not (tmp_path / "coaching.json").exists()

    def test_claude_missing_raises_no_write(self, tmp_path, monkeypatch):
        self._patch(monkeypatch)
        monkeypatch.setattr(R.shutil, "which", lambda *_: None)
        monkeypatch.setattr(R, "get_config", lambda: {"profile": {"claude_bin": "/nonexistent/claude-xyz"}})
        with pytest.raises(R.CoachError, match="Claude CLI not found"):
            R.run_coach(None, reports_dir=tmp_path)
        assert not (tmp_path / "coaching.json").exists()

    def test_nonzero_exit_raises_no_write(self, tmp_path, monkeypatch):
        self._patch(monkeypatch)
        monkeypatch.setattr(R.subprocess, "run", _fake_run(1, "", "auth required"))
        with pytest.raises(R.CoachError, match="exited 1"):
            R.run_coach(None, reports_dir=tmp_path, claude_bin="claude-dummy")
        assert not (tmp_path / "coaching.json").exists()

    def test_is_error_envelope_raises(self, tmp_path, monkeypatch):
        self._patch(monkeypatch)
        monkeypatch.setattr(R.subprocess, "run", _fake_run(0, _envelope("boom", is_error=True)))
        with pytest.raises(R.CoachError, match="reported an error"):
            R.run_coach(None, reports_dir=tmp_path, claude_bin="claude-dummy")
        assert not (tmp_path / "coaching.json").exists()

    def test_no_array_in_response_raises(self, tmp_path, monkeypatch):
        self._patch(monkeypatch)
        monkeypatch.setattr(R.subprocess, "run", _fake_run(0, _envelope("I have no JSON for you.")))
        with pytest.raises(R.CoachError, match="No JSON insights array"):
            R.run_coach(None, reports_dir=tmp_path, claude_bin="claude-dummy")
        assert not (tmp_path / "coaching.json").exists()

    def test_short_body_from_model_rejected_no_write(self, tmp_path, monkeypatch):
        self._patch(monkeypatch)
        bad = _envelope('[{"type":"info","title":"x","body":"short"}]')
        monkeypatch.setattr(R.subprocess, "run", _fake_run(0, bad))
        with pytest.raises(R.CoachError, match="Error:"):
            R.run_coach(None, reports_dir=tmp_path, claude_bin="claude-dummy")
        assert not (tmp_path / "coaching.json").exists()

    def test_timeout_raises_no_write(self, tmp_path, monkeypatch):
        self._patch(monkeypatch)
        def boom(*a, **k):
            raise subprocess.TimeoutExpired(cmd="claude", timeout=180)
        monkeypatch.setattr(R.subprocess, "run", boom)
        with pytest.raises(R.CoachError, match="timed out"):
            R.run_coach(None, reports_dir=tmp_path, claude_bin="claude-dummy")
        assert not (tmp_path / "coaching.json").exists()

    def test_raw_text_response_without_envelope(self, tmp_path, monkeypatch):
        # older/alt CLI: stdout is the raw array text, not a JSON envelope
        self._patch(monkeypatch)
        monkeypatch.setattr(R.subprocess, "run", _fake_run(0, VALID))
        res = R.run_coach(None, reports_dir=tmp_path, claude_bin="claude-dummy")
        assert res["saved"] is True and (tmp_path / "coaching.json").exists()
