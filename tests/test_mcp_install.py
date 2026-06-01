"""Tests for fit/mcp_install.py — MCP client registration."""

import json

import pytest

from fit import mcp_install as mi


# ── merge_server_entry (pure) ──


class TestMergeServerEntry:
    def test_adds_to_empty_config(self):
        cfg, changed = mi.merge_server_entry({}, "fit", {"command": "python", "args": ["s.py"]})
        assert changed is True
        assert cfg["mcpServers"]["fit"] == {"command": "python", "args": ["s.py"]}

    def test_preserves_unrelated_keys(self):
        original = {"preferences": {"theme": "dark"}, "coworkUserFilesPath": "/x"}
        cfg, changed = mi.merge_server_entry(original, "fit", {"command": "py", "args": []})
        assert changed is True
        assert cfg["preferences"] == {"theme": "dark"}
        assert cfg["coworkUserFilesPath"] == "/x"

    def test_preserves_other_mcp_servers(self):
        original = {"mcpServers": {"other": {"command": "node", "args": ["x.js"]}}}
        cfg, _ = mi.merge_server_entry(original, "fit", {"command": "py", "args": []})
        assert cfg["mcpServers"]["other"] == {"command": "node", "args": ["x.js"]}
        assert "fit" in cfg["mcpServers"]

    def test_idempotent_when_identical(self):
        entry = {"command": "python", "args": ["s.py"]}
        original = {"mcpServers": {"fit": entry}}
        cfg, changed = mi.merge_server_entry(original, "fit", entry)
        assert changed is False
        assert cfg["mcpServers"]["fit"] == entry

    def test_updates_when_entry_differs(self):
        original = {"mcpServers": {"fit": {"command": "old", "args": ["a"]}}}
        cfg, changed = mi.merge_server_entry(original, "fit", {"command": "new", "args": ["b"]})
        assert changed is True
        assert cfg["mcpServers"]["fit"]["command"] == "new"

    def test_does_not_mutate_input(self):
        original = {"mcpServers": {}}
        mi.merge_server_entry(original, "fit", {"command": "py", "args": []})
        assert original == {"mcpServers": {}}  # unchanged


# ── load_json ──


class TestLoadJson:
    def test_missing_file_returns_empty(self, tmp_path):
        assert mi.load_json(tmp_path / "nope.json") == {}

    def test_malformed_raises_valueerror(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{not json")
        with pytest.raises(ValueError, match="not valid JSON"):
            mi.load_json(p)

    def test_reads_valid(self, tmp_path):
        p = tmp_path / "ok.json"
        p.write_text('{"a": 1}')
        assert mi.load_json(p) == {"a": 1}


# ── install_desktop ──


class TestInstallDesktop:
    def test_creates_config_when_absent(self, tmp_path):
        cfg = tmp_path / "claude_desktop_config.json"
        res = mi.install_desktop(python_exe="/usr/bin/python3", config_path=cfg)
        assert res["action"] == "installed"
        data = json.loads(cfg.read_text())
        assert data["mcpServers"]["fit"]["command"] == "/usr/bin/python3"

    def test_unchanged_on_second_run(self, tmp_path):
        cfg = tmp_path / "c.json"
        mi.install_desktop(python_exe="/usr/bin/python3", config_path=cfg)
        res = mi.install_desktop(python_exe="/usr/bin/python3", config_path=cfg)
        assert res["action"] == "unchanged"

    def test_updated_when_interpreter_changes(self, tmp_path):
        cfg = tmp_path / "c.json"
        mi.install_desktop(python_exe="/old/python", config_path=cfg)
        res = mi.install_desktop(python_exe="/new/python", config_path=cfg)
        assert res["action"] == "updated"
        data = json.loads(cfg.read_text())
        assert data["mcpServers"]["fit"]["command"] == "/new/python"

    def test_preserves_existing_keys(self, tmp_path):
        cfg = tmp_path / "c.json"
        cfg.write_text(json.dumps({"preferences": {"x": 1},
                                   "mcpServers": {"other": {"command": "n", "args": []}}}))
        mi.install_desktop(python_exe="/usr/bin/python3", config_path=cfg)
        data = json.loads(cfg.read_text())
        assert data["preferences"] == {"x": 1}
        assert data["mcpServers"]["other"] == {"command": "n", "args": []}
        assert "fit" in data["mcpServers"]

    def test_malformed_config_raises(self, tmp_path):
        cfg = tmp_path / "c.json"
        cfg.write_text("{broken")
        with pytest.raises(ValueError):
            mi.install_desktop(python_exe="/usr/bin/python3", config_path=cfg)


# ── verify_claude_code ──


class TestVerifyClaudeCode:
    def test_ok_when_fit_present(self, tmp_path):
        p = tmp_path / ".mcp.json"
        p.write_text(json.dumps({"mcpServers": {"fit": {"command": "python", "args": ["mcp/server.py"]}}}))
        res = mi.verify_claude_code(config_path=p)
        assert res["ok"] is True

    def test_missing_file(self, tmp_path):
        res = mi.verify_claude_code(config_path=tmp_path / "nope.json")
        assert res["ok"] is False
        assert res["reason"] == "missing"

    def test_no_fit_entry(self, tmp_path):
        p = tmp_path / ".mcp.json"
        p.write_text(json.dumps({"mcpServers": {"other": {"command": "n", "args": []}}}))
        res = mi.verify_claude_code(config_path=p)
        assert res["ok"] is False
        assert res["reason"] == "no_fit_entry"

    def test_invalid_json(self, tmp_path):
        p = tmp_path / ".mcp.json"
        p.write_text("{bad")
        res = mi.verify_claude_code(config_path=p)
        assert res["ok"] is False
        assert res["reason"] == "invalid_json"


# ── uninstall_desktop ──


class TestUninstallDesktop:
    def test_removes_entry(self, tmp_path):
        cfg = tmp_path / "c.json"
        mi.install_desktop(python_exe="/usr/bin/python3", config_path=cfg)
        res = mi.uninstall_desktop(config_path=cfg)
        assert res["action"] == "removed"
        data = json.loads(cfg.read_text())
        assert "mcpServers" not in data  # emptied block dropped

    def test_absent_when_not_registered(self, tmp_path):
        cfg = tmp_path / "c.json"
        cfg.write_text(json.dumps({"preferences": {}}))
        res = mi.uninstall_desktop(config_path=cfg)
        assert res["action"] == "absent"

    def test_keeps_other_servers(self, tmp_path):
        cfg = tmp_path / "c.json"
        cfg.write_text(json.dumps({"mcpServers": {"fit": {"command": "p", "args": []},
                                                  "other": {"command": "n", "args": []}}}))
        mi.uninstall_desktop(config_path=cfg)
        data = json.loads(cfg.read_text())
        assert "fit" not in data["mcpServers"]
        assert "other" in data["mcpServers"]


# ── path helpers ──


class TestPaths:
    def test_server_script_exists(self):
        # The packaged server must actually be where we tell clients to find it.
        assert mi.server_script().name == "server.py"
        assert mi.server_script().exists()

    def test_desktop_entry_uses_running_interpreter_by_default(self):
        import sys
        entry = mi.desktop_server_entry()
        assert entry["command"] == sys.executable
        assert entry["args"][0].endswith("server.py")
