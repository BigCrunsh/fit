"""Register the fit MCP server with local Claude clients.

Two clients can spawn the stdio MCP server:

  - Claude Code reads ``.mcp.json`` at the repo root (committed, relative
    paths — it runs from the repo dir).
  - Claude Desktop reads its own ``claude_desktop_config.json`` in an
    OS-specific application-support directory, and runs from an arbitrary
    cwd — so it needs ABSOLUTE paths and the exact interpreter that has
    ``fit`` installed.

claude.ai (web) cannot reach a local stdio server, so it's reported as
unsupported rather than silently skipped.

The Desktop install MERGES into the existing config — it never clobbers
unrelated keys (preferences, coworkUserFilesPath, other MCP servers).
Re-running is idempotent: it only rewrites when the ``fit`` entry would
actually change.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SERVER_NAME = "fit"


def repo_root() -> Path:
    """Repo root = parent of the fit/ package directory."""
    return Path(__file__).resolve().parent.parent


def server_script() -> Path:
    """Absolute path to mcp/server.py."""
    return repo_root() / "mcp" / "server.py"


def desktop_config_path() -> Path:
    """OS-specific path to Claude Desktop's config file.

    macOS:   ~/Library/Application Support/Claude/claude_desktop_config.json
    Windows: %APPDATA%/Claude/claude_desktop_config.json
    Linux:   ~/.config/Claude/claude_desktop_config.json
    """
    home = Path.home()
    if sys.platform == "darwin":
        base = home / "Library" / "Application Support"
    elif sys.platform.startswith("win"):
        import os

        base = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    else:
        import os

        base = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
    return base / "Claude" / "claude_desktop_config.json"


def claude_code_config_path() -> Path:
    """Path to the repo's committed .mcp.json (Claude Code)."""
    return repo_root() / ".mcp.json"


def desktop_server_entry(python_exe: str | None = None,
                         script: Path | None = None) -> dict:
    """The {command, args} entry for Desktop — absolute paths.

    Defaults to the running interpreter (``sys.executable``) so it always
    points at the environment that has ``fit`` + ``mcp`` installed, never a
    hardcoded path that breaks on a Python upgrade.
    """
    python_exe = python_exe or sys.executable
    script = script or server_script()
    return {"command": python_exe, "args": [str(script)]}


def merge_server_entry(config: dict, name: str, entry: dict) -> tuple[dict, bool]:
    """Merge one MCP server entry into a config dict (pure).

    Returns (new_config, changed). ``changed`` is False when the entry is
    already present and identical — lets callers skip the write and report
    "already up to date". Does not mutate the input.
    """
    new_config = json.loads(json.dumps(config))  # deep copy via round-trip
    servers = new_config.setdefault("mcpServers", {})
    if servers.get(name) == entry:
        return new_config, False
    servers[name] = entry
    return new_config, True


def load_json(path: Path) -> dict:
    """Read a JSON config file, returning {} if it doesn't exist.

    Raises ValueError (not JSONDecodeError) on malformed content so the
    caller can surface a clean message instead of a traceback.
    """
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise ValueError(f"{path} is not valid JSON: {e}") from e


def write_json_atomic(path: Path, data: dict) -> None:
    """Write JSON to a temp file then rename — never leaves a half-written config."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.rename(path)


def install_desktop(python_exe: str | None = None,
                    config_path: Path | None = None) -> dict:
    """Register (or update) the fit server in Claude Desktop's config.

    Returns a result dict: {action, path, entry} where action is one of
    'installed', 'updated', 'unchanged'.
    """
    config_path = config_path or desktop_config_path()
    existing = load_json(config_path)
    had_entry = SERVER_NAME in existing.get("mcpServers", {})
    entry = desktop_server_entry(python_exe)
    merged, changed = merge_server_entry(existing, SERVER_NAME, entry)
    if not changed:
        action = "unchanged"
    else:
        write_json_atomic(config_path, merged)
        action = "updated" if had_entry else "installed"
    return {"action": action, "path": config_path, "entry": entry}


def verify_claude_code(config_path: Path | None = None) -> dict:
    """Check the repo .mcp.json registers the fit server.

    Returns {ok, path, reason}. ok=True means Claude Code will spawn it.
    Does not modify the file — it's committed and the canonical source.
    """
    config_path = config_path or claude_code_config_path()
    if not config_path.exists():
        return {"ok": False, "path": config_path, "reason": "missing"}
    try:
        data = json.loads(config_path.read_text())
    except json.JSONDecodeError:
        return {"ok": False, "path": config_path, "reason": "invalid_json"}
    if SERVER_NAME not in data.get("mcpServers", {}):
        return {"ok": False, "path": config_path, "reason": "no_fit_entry"}
    return {"ok": True, "path": config_path, "reason": "ok"}


def uninstall_desktop(config_path: Path | None = None) -> dict:
    """Remove the fit server from Claude Desktop's config (idempotent).

    Returns {action, path} where action is 'removed' or 'absent'.
    """
    config_path = config_path or desktop_config_path()
    existing = load_json(config_path)
    servers = existing.get("mcpServers", {})
    if SERVER_NAME not in servers:
        return {"action": "absent", "path": config_path}
    del servers[SERVER_NAME]
    # Drop an emptied mcpServers block to keep the config tidy.
    if not servers:
        existing.pop("mcpServers", None)
    write_json_atomic(config_path, existing)
    return {"action": "removed", "path": config_path}
