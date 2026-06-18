"""Coaching-notes writer — validates insights and atomically writes reports/coaching.json.

Ported verbatim from the former MCP `save_coaching_notes` tool; now called by `fit coach`.
"""

import json
from pathlib import Path

from fit.config import get_config


def save_coaching_notes(insights_json: str, reports_dir=None) -> str:
    """Save coaching insights to reports/coaching.json. Pass a JSON array where EACH insight MUST have: type (critical/warning/positive/info/target), title (short), and body (FULL analysis paragraph with specific numbers and recommendations — minimum 20 chars, typically 2-5 sentences). Insights without body text will be rejected."""
    from datetime import datetime

    try:
        data = json.loads(insights_json)
    except json.JSONDecodeError as e:
        return f"Error: Invalid JSON: {e}"

    if "insights" not in data:
        if isinstance(data, list):
            data = {"insights": data}
        else:
            return "Error: JSON must contain an 'insights' array."

    # Validate each insight has type, title, AND body with actual content
    errors = []
    for i, insight in enumerate(data.get("insights", [])):
        if not insight.get("type"):
            errors.append(f"Insight {i}: missing 'type' (critical/warning/positive/info/target)")
        if not insight.get("title"):
            errors.append(f"Insight {i}: missing 'title'")
        if not insight.get("body") or len(str(insight.get("body", ""))) < 20:
            errors.append(f"Insight {i} ('{insight.get('title', '?')}'): missing or too short 'body' — "
                          "each insight MUST include the full analysis paragraph, not just a title. "
                          "The body should contain specific numbers, context, and actionable recommendations.")
    if errors:
        return "Error: Insights validation failed. Fix these issues and re-save:\n" + "\n".join(errors)

    data["generated_at"] = datetime.now().isoformat()
    data["report_date"] = datetime.now().strftime("%Y-%m-%d")

    reports_dir = (Path(reports_dir) if reports_dir is not None
                   else Path(get_config()["sync"]["db_path"]).expanduser().parent / "reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    coaching_path = reports_dir / "coaching.json"

    # Archive previous coaching notes to history (append, never lose)
    history_path = reports_dir / "coaching_history.json"
    if coaching_path.exists():
        try:
            prev = json.loads(coaching_path.read_text())
            history = json.loads(history_path.read_text()) if history_path.exists() else []
            history.append(prev)
            history_path.write_text(json.dumps(history, indent=2))
        except Exception:
            pass  # Don't fail the save if archiving fails

    # Atomic write: temp file + rename
    tmp_path = coaching_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(data, indent=2))
    tmp_path.rename(coaching_path)

    n = len(data.get("insights", []))
    return f"Saved {n} coaching insights to {coaching_path} (previous notes archived to coaching_history.json)"
