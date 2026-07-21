"""Runner — `fit coach` shells out to the headless Claude CLI and persists the result.

Assemble context (fit/coaching/context) → invoke `claude -p --append-system-prompt <instructions>
--output-format json <context>` → extract the assistant text → pull out the insights JSON array →
validate + save (fit/coaching/save). Fails CLOSED: any failure (binary missing, nonzero exit, auth,
timeout, unparseable/invalid response) raises CoachError and writes nothing — coaching.json is never
corrupted.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from fit.config import get_config
from fit.coaching.context import assemble_coaching_context
from fit.coaching.prompt import COACHING_INSTRUCTIONS
from fit.coaching.save import save_coaching_notes

DEFAULT_TIMEOUT_S = 180

_ANSI_CSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _strip_ansi(text: str) -> str:
    """Strip ANSI CSI escape sequences (cursor moves, line erases, color resets) that a terminal
    UI's spinner/redraw logic can leak onto stdout even when it isn't a TTY."""
    return _ANSI_CSI_RE.sub("", text)


def _find_json_value(text: str, open_char: str):
    """Scan `text` for the first complete, valid JSON value starting with `open_char` ("{" or "[").

    Unlike a naive find/rfind of the opening/closing character, this validates the whole value at
    each candidate offset via `json.JSONDecoder.raw_decode` — so a stray bracket from a leaked
    escape code or from prose elsewhere in the text can't be mistaken for the real payload's
    delimiter. Returns None if no valid value is found."""
    decoder = json.JSONDecoder()
    start = 0
    while True:
        idx = text.find(open_char, start)
        if idx == -1:
            return None
        try:
            obj, _ = decoder.raw_decode(text, idx)
            return obj
        except json.JSONDecodeError:
            start = idx + 1


class CoachError(Exception):
    """A coaching run failed — surfaced to the CLI as an actionable message; nothing is written."""


def _resolve_claude(config) -> str:
    """Locate the Claude Code CLI: config profile.claude_bin → PATH → ~/.local/bin/claude."""
    prof = config.get("profile", {})
    cand = prof.get("claude_bin") or shutil.which("claude") or str(Path.home() / ".local/bin/claude")
    if shutil.which(cand) is None and not Path(cand).exists():
        raise CoachError(
            "Claude CLI not found. `fit coach` shells out to the Claude Code CLI "
            "(https://docs.claude.com/en/docs/claude-code) — install it and ensure `claude` is on "
            "PATH, or set `profile.claude_bin` in config. (This is NOT a pip package.)"
        )
    return cand


def _extract_assistant_text(stdout: str) -> str:
    """Pull the assistant's final text out of `claude -p --output-format json`'s envelope.

    The envelope is a JSON object with the text under `result`; if `is_error` is set, fail. If stdout
    isn't JSON (older/alt CLI) — or the envelope is present but surrounded by noise, e.g. leaked
    terminal escape codes — treat it as raw text and let `_extract_insights_json` find the array."""
    stdout = _strip_ansi(stdout).strip()
    if not stdout:
        raise CoachError("Claude returned no output.")
    env = _find_json_value(stdout, "{")
    if isinstance(env, dict):
        if env.get("is_error") or env.get("subtype") not in (None, "success"):
            raise CoachError(f"Claude reported an error: {str(env.get('result') or env)[:500]}")
        return str(env.get("result", env.get("text", stdout)))
    return stdout


def _extract_insights_json(text: str) -> str:
    """Lenient extraction of the JSON insights array from the model text (strips stray fences/prose/
    noise around it — validates the whole array rather than assuming the first `[`/last `]` match)."""
    array = _find_json_value(text, "[")
    if not isinstance(array, list):
        raise CoachError("No JSON insights array found in the model response:\n" + text[:500])
    return json.dumps(array)


def run_coach(conn, *, reports_dir=None, save=True, days=None, model=None,
              timeout=None, claude_bin=None):
    """Run a coaching analysis. Returns {text, insights, insights_json, saved}. Raises CoachError on
    any failure (and writes nothing). `days` is reserved for future context windowing."""
    config = get_config()
    claude = claude_bin or _resolve_claude(config)
    timeout = timeout or config.get("profile", {}).get("coaching_timeout_s", DEFAULT_TIMEOUT_S)

    context = assemble_coaching_context(conn)
    cmd = [claude, "-p", "--append-system-prompt", COACHING_INSTRUCTIONS, "--output-format", "json"]
    if model:
        cmd += ["--model", model]
    cmd.append(context)

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise CoachError(f"Claude timed out after {timeout}s "
                         "(raise with --timeout or config profile.coaching_timeout_s).")
    except FileNotFoundError:
        raise CoachError(f"Claude CLI not executable at {claude!r}.")
    if proc.returncode != 0:
        raise CoachError(f"Claude exited {proc.returncode}: "
                         f"{(proc.stderr or proc.stdout or '').strip()[:500]}")

    text = _extract_assistant_text(proc.stdout)
    insights_json = _extract_insights_json(text)

    if save:
        result = save_coaching_notes(insights_json, reports_dir=reports_dir)
        if result.startswith("Error:"):       # validation failed → save wrote NOTHING
            raise CoachError(result)
    else:
        # validate shape without writing (a non-empty JSON array); save runs the full validation
        try:
            parsed = json.loads(insights_json)
        except json.JSONDecodeError as e:
            raise CoachError(f"Insights are not valid JSON: {e}")
        if not isinstance(parsed, list) or not parsed:
            raise CoachError("Insights must be a non-empty JSON array.")

    return {"text": text, "insights_json": insights_json, "saved": bool(save)}
