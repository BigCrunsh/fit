"""Tests for fit/config.py — three-layer config loading, deep merge, placeholder resolution."""


import pytest
import yaml

from fit.config import get_config, _deep_merge, _resolve_placeholders


# ════════════════════════════════════════════════════════════════
# Deep Merge
# ════════════════════════════════════════════════════════════════


class TestDeepMerge:
    # Happy
    def test_simple_override(self):
        result = _deep_merge({"a": 1}, {"a": 2})
        assert result == {"a": 2}

    def test_nested_merge(self):
        base = {"a": {"b": 1, "c": 2}}
        override = {"a": {"b": 99}}
        result = _deep_merge(base, override)
        assert result == {"a": {"b": 99, "c": 2}}

    def test_new_key(self):
        result = _deep_merge({"a": 1}, {"b": 2})
        assert result == {"a": 1, "b": 2}

    def test_deeply_nested(self):
        base = {"a": {"b": {"c": {"d": 1}}}}
        override = {"a": {"b": {"c": {"d": 99, "e": 100}}}}
        result = _deep_merge(base, override)
        assert result["a"]["b"]["c"]["d"] == 99
        assert result["a"]["b"]["c"]["e"] == 100

    # Unhappy
    def test_empty_base(self):
        result = _deep_merge({}, {"a": 1})
        assert result == {"a": 1}

    def test_empty_override(self):
        result = _deep_merge({"a": 1}, {})
        assert result == {"a": 1}

    def test_both_empty(self):
        result = _deep_merge({}, {})
        assert result == {}

    def test_list_vs_dict_override(self):
        """Override replaces list with dict (override wins on type conflict)."""
        result = _deep_merge({"a": [1, 2, 3]}, {"a": {"x": 1}})
        assert result == {"a": {"x": 1}}

    def test_dict_vs_list_override(self):
        """Override replaces dict with list."""
        result = _deep_merge({"a": {"x": 1}}, {"a": [1, 2]})
        assert result == {"a": [1, 2]}

    def test_scalar_vs_dict_override(self):
        result = _deep_merge({"a": "string"}, {"a": {"nested": True}})
        assert result == {"a": {"nested": True}}

    def test_none_override(self):
        result = _deep_merge({"a": 1}, {"a": None})
        assert result == {"a": None}

    def test_base_not_mutated(self):
        """Original base dict should not be mutated."""
        base = {"a": 1, "b": 2}
        _deep_merge(base, {"a": 99})
        assert base == {"a": 1, "b": 2}

    def test_nested_base_not_mutated(self):
        base = {"a": {"b": 1}}
        _deep_merge(base, {"a": {"c": 2}})
        assert "c" not in base["a"]


# ════════════════════════════════════════════════════════════════
# Placeholder Resolution
# ════════════════════════════════════════════════════════════════


class TestPlaceholders:
    # Happy
    def test_env_var_resolved(self, monkeypatch):
        monkeypatch.setenv("TEST_VAR", "hello")
        result = _resolve_placeholders("${TEST_VAR}")
        assert result == "hello"

    def test_default_used(self):
        result = _resolve_placeholders("${NONEXISTENT_XYZ:-fallback}")
        assert result == "fallback"

    def test_env_overrides_default(self, monkeypatch):
        monkeypatch.setenv("TEST_VAR", "from_env")
        result = _resolve_placeholders("${TEST_VAR:-default}")
        assert result == "from_env"

    def test_nested_dict(self, monkeypatch):
        monkeypatch.setenv("VAR1", "a")
        monkeypatch.setenv("VAR2", "b")
        result = _resolve_placeholders({"x": "${VAR1}", "y": {"z": "${VAR2}"}})
        assert result == {"x": "a", "y": {"z": "b"}}

    def test_list_resolution(self, monkeypatch):
        monkeypatch.setenv("VAR1", "item")
        result = _resolve_placeholders(["${VAR1}", "literal"])
        assert result == ["item", "literal"]

    # Unhappy
    def test_unresolved_raises(self):
        with pytest.raises(ValueError, match="MISSING_VAR"):
            _resolve_placeholders("${MISSING_VAR}")

    def test_empty_default(self):
        """${VAR:-} should resolve to empty string."""
        result = _resolve_placeholders("${NONEXISTENT_XYZ:-}")
        assert result == ""

    def test_multiple_placeholders_in_one_string(self, monkeypatch):
        monkeypatch.setenv("A", "hello")
        monkeypatch.setenv("B", "world")
        result = _resolve_placeholders("${A} ${B}")
        assert result == "hello world"

    def test_multiple_placeholders_one_missing(self, monkeypatch):
        monkeypatch.setenv("A", "hello")
        with pytest.raises(ValueError, match="MISSING_B"):
            _resolve_placeholders("${A} ${MISSING_B}")

    def test_non_string_passthrough(self):
        """Integers, booleans, etc. should pass through unchanged."""
        assert _resolve_placeholders(42) == 42
        assert _resolve_placeholders(True) is True
        assert _resolve_placeholders(None) is None

    def test_nested_placeholder_in_default(self):
        """Default value with $ should be taken literally (not recursively resolved)."""
        result = _resolve_placeholders("${MISSING:-${literal}}")
        assert result == "${literal}"

    def test_placeholder_at_path_in_error(self):
        with pytest.raises(ValueError, match="MISSING"):
            _resolve_placeholders({"a": {"b": "${MISSING}"}})


# ════════════════════════════════════════════════════════════════
# Config Loading (get_config)
# ════════════════════════════════════════════════════════════════


class TestConfigLoading:
    # Happy
    def test_template_only(self, tmp_path):
        (tmp_path / "config.yaml").write_text(yaml.dump({"profile": {"name": "template"}}))
        config = get_config(tmp_path)
        assert config["profile"]["name"] == "template"

    def test_local_overrides_template(self, tmp_path):
        (tmp_path / "config.yaml").write_text(yaml.dump({"profile": {"name": "template", "age": 30}}))
        (tmp_path / "config.local.yaml").write_text(yaml.dump({"profile": {"name": "local"}}))
        config = get_config(tmp_path)
        assert config["profile"]["name"] == "local"
        assert config["profile"]["age"] == 30

    def test_env_var_override(self, tmp_path, monkeypatch):
        (tmp_path / "config.yaml").write_text(yaml.dump({"profile": {"name": "${TEST_FIT_NAME}"}}))
        monkeypatch.setenv("TEST_FIT_NAME", "from_env")
        config = get_config(tmp_path)
        assert config["profile"]["name"] == "from_env"

    def test_default_placeholder(self, tmp_path):
        (tmp_path / "config.yaml").write_text(yaml.dump({"city": "${CITY:-Berlin}"}))
        config = get_config(tmp_path)
        assert config["city"] == "Berlin"

    def test_default_config_searches_multiple_locations(self, tmp_path):
        """get_config(None) searches repo root, ~/.fit, and cwd."""
        # With no args, it should find config.yaml in the repo root (package parent)
        config = get_config()
        assert config is not None  # found it somewhere

    def test_explicit_dir_overrides_search(self, tmp_path):
        """get_config(path) uses that exact path."""
        (tmp_path / "config.yaml").write_text(yaml.dump({"custom": True}))
        config = get_config(tmp_path)
        assert config["custom"] is True

    # Unhappy
    def test_missing_config_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            get_config(tmp_path / "nonexistent")

    def test_unresolved_placeholder_raises(self, tmp_path):
        (tmp_path / "config.yaml").write_text(yaml.dump({"profile": {"name": "${NONEXISTENT_VAR}"}}))
        with pytest.raises(ValueError, match="NONEXISTENT_VAR"):
            get_config(tmp_path)

    def test_empty_yaml_file(self, tmp_path):
        """Empty YAML file should return empty dict."""
        (tmp_path / "config.yaml").write_text("")
        config = get_config(tmp_path)
        assert config == {}

    def test_malformed_yaml_raises(self, tmp_path):
        """Malformed YAML should raise."""
        (tmp_path / "config.yaml").write_text("{{invalid yaml: [")
        with pytest.raises(yaml.YAMLError):
            get_config(tmp_path)

    def test_empty_local_yaml(self, tmp_path):
        """Empty local YAML should not break merge."""
        (tmp_path / "config.yaml").write_text(yaml.dump({"x": 1}))
        (tmp_path / "config.local.yaml").write_text("")
        config = get_config(tmp_path)
        assert config["x"] == 1

    def test_local_adds_new_keys(self, tmp_path):
        (tmp_path / "config.yaml").write_text(yaml.dump({"a": 1}))
        (tmp_path / "config.local.yaml").write_text(yaml.dump({"b": 2}))
        config = get_config(tmp_path)
        assert config["a"] == 1
        assert config["b"] == 2

    def test_config_with_list_values(self, tmp_path):
        (tmp_path / "config.yaml").write_text(yaml.dump({"items": [1, 2, 3]}))
        config = get_config(tmp_path)
        assert config["items"] == [1, 2, 3]

    def test_local_replaces_list(self, tmp_path):
        (tmp_path / "config.yaml").write_text(yaml.dump({"items": [1, 2]}))
        (tmp_path / "config.local.yaml").write_text(yaml.dump({"items": [3, 4, 5]}))
        config = get_config(tmp_path)
        assert config["items"] == [3, 4, 5]
