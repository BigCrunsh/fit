"""Tests for fit/config.py — three-layer config loading."""

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from fit.config import get_config


class TestConfigLoading:
    def test_template_only(self, tmp_path):
        (tmp_path / "config.yaml").write_text(yaml.dump({"profile": {"name": "template"}}))
        config = get_config(tmp_path)
        assert config["profile"]["name"] == "template"

    def test_local_overrides_template(self, tmp_path):
        (tmp_path / "config.yaml").write_text(yaml.dump({"profile": {"name": "template", "age": 30}}))
        (tmp_path / "config.local.yaml").write_text(yaml.dump({"profile": {"name": "local"}}))
        config = get_config(tmp_path)
        assert config["profile"]["name"] == "local"
        assert config["profile"]["age"] == 30  # preserved from template

    def test_env_var_override(self, tmp_path, monkeypatch):
        (tmp_path / "config.yaml").write_text(yaml.dump({"profile": {"name": "${TEST_FIT_NAME}"}}))
        monkeypatch.setenv("TEST_FIT_NAME", "from_env")
        config = get_config(tmp_path)
        assert config["profile"]["name"] == "from_env"

    def test_unresolved_placeholder_raises(self, tmp_path):
        (tmp_path / "config.yaml").write_text(yaml.dump({"profile": {"name": "${NONEXISTENT_VAR}"}}))
        with pytest.raises(ValueError, match="NONEXISTENT_VAR"):
            get_config(tmp_path)

    def test_default_placeholder(self, tmp_path):
        (tmp_path / "config.yaml").write_text(yaml.dump({"city": "${CITY:-Berlin}"}))
        config = get_config(tmp_path)
        assert config["city"] == "Berlin"

    def test_missing_config_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            get_config(tmp_path / "nonexistent")
