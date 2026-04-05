"""Rule-based headline engine for the Today tab."""


def generate_headline(readiness: int | None, acwr: float | None, phase: dict | None,
                      last_checkin_date: str | None, today: str = None) -> str:
    """Generate a daily headline sentence based on current state.

    Returns a single actionable sentence for the Today tab.
    """
    parts = []

    # Recovery signal
    if readiness is not None:
        if readiness < 50:
            parts.append(f"Recovery day recommended (readiness {readiness}).")
        elif readiness >= 75:
            parts.append("Ready for training.")
        else:
            parts.append(f"Moderate readiness ({readiness}).")

    # ACWR safety
    if acwr is not None:
        if acwr > 1.5:
            parts.append(f"Training spike detected — ACWR {acwr:.2f}. Reduce load.")
        elif acwr > 1.3:
            parts.append(f"ACWR {acwr:.2f} approaching limit. Keep it easy.")
        elif acwr < 0.6:
            parts.append(f"ACWR {acwr:.2f} — detraining risk. Increase volume gradually.")

    # Phase-aware session suggestion
    if phase and readiness and readiness >= 50:
        phase_name = phase.get("name", "")
        quality_target = 0
        if phase.get("targets"):
            import json
            targets = json.loads(phase["targets"]) if isinstance(phase["targets"], str) else phase["targets"]
            qt = targets.get("quality_sessions_per_week", 0)
            quality_target = qt[0] if isinstance(qt, list) else qt

        if quality_target == 0:
            parts.append(f"{phase_name}: easy Z2 runs only, no hard efforts.")
        elif readiness >= 75:
            parts.append(f"{phase_name}: a quality session (tempo or intervals) is appropriate today.")
        else:
            parts.append(f"{phase_name}: easy run today, save quality for a high-readiness day.")

    # Stale checkin
    if last_checkin_date and today:
        if last_checkin_date < today:
            parts.append("No check-in today — run `fit checkin` before training.")

    if not parts:
        parts.append("Sync data to see your training headline.")

    return " ".join(parts)
