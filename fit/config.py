"""Three-layer config loading: config.yaml → config.local.yaml → env vars."""

import logging
import os
import re
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_PLACEHOLDER_RE = re.compile(r"\$\{([^}]+)\}")


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge override into base. Override wins on conflicts."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _resolve_placeholders(obj: Any, path: str = "") -> Any:
    """Walk a nested dict/list and resolve ${VAR} placeholders from env vars.

    Supports defaults: ${VAR:-default}. Raises ValueError for unresolved
    required placeholders. Empty string values (from ${VAR:-}) are kept as-is.
    """
    if isinstance(obj, str):
        def _replace(match):
            expr = match.group(1)
            if ":-" in expr:
                var_name, default = expr.split(":-", 1)
                return os.environ.get(var_name, default)
            value = os.environ.get(expr)
            if value is None:
                raise ValueError(f"Config placeholder ${{{expr}}} at '{path}' has no value. "
                                 f"Set it in config.local.yaml or as environment variable {expr}.")
            return value

        resolved = _PLACEHOLDER_RE.sub(_replace, obj)
        return resolved
    elif isinstance(obj, dict):
        return {k: _resolve_placeholders(v, f"{path}.{k}") for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_resolve_placeholders(item, f"{path}[{i}]") for i, item in enumerate(obj)]
    return obj


def get_config(config_dir: Path | None = None) -> dict:
    """Load config from config.yaml → config.local.yaml → env vars.

    Args:
        config_dir: Directory containing config files. Defaults to current working directory.

    Returns:
        Merged and resolved config dict.
    """
    if config_dir is None:
        config_dir = Path.cwd()

    # Layer 1: template config (committed)
    config_path = config_dir / "config.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"Config template not found: {config_path}")

    with open(config_path) as f:
        config = yaml.safe_load(f) or {}

    logger.debug("Loaded config template from %s", config_path)

    # Layer 2: local config (gitignored, optional)
    local_path = config_dir / "config.local.yaml"
    if local_path.exists():
        with open(local_path) as f:
            local_config = yaml.safe_load(f) or {}
        config = _deep_merge(config, local_config)
        logger.debug("Merged local config from %s", local_path)
    else:
        logger.debug("No local config at %s", local_path)

    # Layer 3: resolve env var placeholders
    config = _resolve_placeholders(config)

    logger.info("Config loaded: profile.name=%s, sync.db_path=%s",
                config.get("profile", {}).get("name", "?"),
                config.get("sync", {}).get("db_path", "?"))

    return config
