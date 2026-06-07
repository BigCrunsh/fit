"""Sync pipeline: Garmin → normalize → weather → store."""

import logging
import sqlite3
from datetime import date, timedelta

from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn, TimeElapsedColumn

from fit import garmin, weather
from fit.analysis import RUNNING_TYPES_SQL, enrich_activity, compute_weekly_agg
from fit.calibration import (
    add_calibration,
    extract_aet_from_steady_run,
    extract_lthr_from_race,
    extract_max_hr_from_activity,
    get_active_calibration,
)

logger = logging.getLogger(__name__)

# Suppress console logging during progress bars (file logging continues)
_console_suppressed = False


def _sync_lactate_threshold(conn: sqlite3.Connection, api) -> bool:
    """Ingest the watch's auto-detected lactate-threshold HR as a device-anchored
    calibration row (method 'device_lt').

    Stored only when the value changes (≥1 bpm) — building an LT time-series without
    daily duplicates. The row is authoritative for the LTHR anchor: above the
    race-avg-HR proxy, below a deliberate human confirm (see DEVICE_METHODS). This
    replaces reverse-engineering LTHR from race HR with the watch's own measurement.
    Best-effort: never blocks a sync.
    """
    try:
        lt = garmin.fetch_lactate_threshold(api)
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("LTHR ingest skipped: %s", e)
        return False
    if not lt or not lt.get("lthr"):
        return False
    value = round(float(lt["lthr"]), 1)
    prev = conn.execute(
        "SELECT value FROM calibration WHERE metric='lthr' AND method='device_lt' "
        "ORDER BY date DESC, created_at DESC LIMIT 1"
    ).fetchone()
    prev_val = float(prev[0]) if prev else None
    if prev_val is not None and abs(prev_val - value) < 1.0:
        return False  # unchanged — keep the existing dated row (no daily duplicates)
    note = "Garmin auto-detected lactate threshold"
    spd = lt.get("lt_speed_mps")
    if spd:
        note += f" (LT speed {spd:.3f} m/s)"
    add_calibration(conn, "lthr", value, "device_lt", "high", date.today(), notes=note)
    logger.info("Ingested Garmin lactate threshold: %.0f bpm", value)
    return True


def run_sync(conn: sqlite3.Connection, config: dict, days: int = 7, full: bool = False,
             download_splits: bool = False) -> dict:
    """Run the full sync pipeline.

    Args:
        download_splits: If True (or config sync.download_fit_files), download .fit files
            and compute per-km splits for running activities.

    Returns dict with counts per data type.
    """
    token_dir = config["sync"]["garmin_token_dir"]
    api = garmin.connect(token_dir)

    # Ingest the watch's auto-detected lactate threshold BEFORE reading the LTHR
    # calibration below, so zone computation uses the freshest device threshold.
    _sync_lactate_threshold(conn, api)

    if full:
        start = date(2024, 1, 1)  # reasonable far-back date
    else:
        start = date.today() - timedelta(days=days)
    end = date.today()

    counts = {"health": 0, "activities": 0, "spo2": 0, "weather": 0, "enriched": 0, "weekly_agg": 0}
    warnings = []

    # Get LTHR calibration for zone computation
    lthr_cal = get_active_calibration(conn, "lthr")
    lthr = int(lthr_cal["value"]) if lthr_cal else None

    # Active max_hr — calibration table wins over the config default. The
    # config max_hr is treated as the initial value; once a higher reading is
    # auto-extracted from an activity, the calibration row becomes the source
    # of truth and zone boundaries scale up accordingly.
    max_hr_cal = get_active_calibration(conn, "max_hr")
    max_hr = int(max_hr_cal["value"]) if max_hr_cal else config["profile"].get("max_hr")
    # AeT (when calibrated) refines the Z2 ceiling on the LTHR ladder.
    aet_cal = get_active_calibration(conn, "aet")
    aet = int(aet_cal["value"]) if aet_cal else None

    total_days = (end - start).days + 1

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        transient=True,
    ) as progress:

        # 1. Health metrics
        task_h = progress.add_task("Health", total=total_days)
        health_rows = garmin.fetch_health(api, start, end)
        for h in health_rows:
            _upsert_health(conn, h)
            progress.advance(task_h)
        progress.update(task_h, completed=total_days)
        counts["health"] = len(health_rows)

        # 2. Activities
        task_a = progress.add_task("Activities", total=None)
        activities = garmin.fetch_activities(api, start, end)
        progress.update(task_a, total=len(activities), completed=0)

        # 3a. Pass 1 — max_hr calibration refresh from raw activity data.
        #
        # We scan EVERY activity in the fetch window (new and previously-seen)
        # before any enrichment runs. Three reasons:
        #   (a) A re-uploaded activity with a corrected peak HR shouldn't be
        #       skipped just because its row already has hr_zone (F2).
        #   (b) If activity #5 in the batch raises max_hr, activities #0..#4
        #       need to be enriched against the new value, not the old one
        #       — which means the calibration must be finalized BEFORE we
        #       enter the enrichment loop (F5).
        #   (c) The activity that triggers the raise should itself enrich
        #       with the new value (F3).
        # extract_max_hr_from_activity only consults raw fields (type, max_hr)
        # so it works fine on unenriched activity dicts.
        from fit.calibration import add_calibration, derive_flags, derive_confidence
        for a in activities:
            candidate_max = extract_max_hr_from_activity(a, max_hr)
            if not candidate_max:
                continue
            try:
                cal_date = date.fromisoformat(a.get("date") or "")
            except ValueError:
                logger.debug("Skipping max_hr extract for activity %s: missing/bad date %r",
                             a.get("id"), a.get("date"))
                continue
            # Race max counts as a hard-effort context (medium); other
            # running activities get `activity_max` method which derive_flags
            # marks as `weak_context` → low confidence.
            method = "race_candidate" if a.get("run_type") == "race" else "activity_max"
            prior_cal = max_hr_cal  # may be None on first run
            flags = derive_flags("max_hr", candidate_max, method, prior_cal)
            confidence = derive_confidence(method, flags)
            add_calibration(
                conn, "max_hr", candidate_max, method, confidence,
                cal_date,
                source_activity_id=a.get("id"),
                notes=f"Auto-extracted from {a.get('name')} ({a.get('distance_km', '?')}km)",
                flags=flags,
            )
            logger.info("max_hr auto-raised to %s bpm from %s (confidence=%s)",
                        int(candidate_max), a.get("name"), confidence)
            max_hr = int(candidate_max)

        # 3b. Pass 2 — enrich new activities using the (possibly-raised) max_hr.
        for i, a in enumerate(activities):
            existing = conn.execute("SELECT hr_zone FROM activities WHERE id = ?", (a["id"],)).fetchone()
            if existing and existing["hr_zone"] is not None:
                _upsert_activity(conn, a)
            else:
                enriched = enrich_activity(a, config, lthr=lthr, max_hr=max_hr, aet=aet)
                _upsert_enriched_activity(conn, enriched)
                counts["enriched"] += 1

                if enriched.get("run_type") == "race":
                    candidate_lthr = extract_lthr_from_race(enriched)
                    if candidate_lthr:
                        try:
                            cal_date = date.fromisoformat(enriched.get("date") or "")
                        except ValueError:
                            logger.debug("Skipping LTHR extract for activity %s: bad date",
                                         enriched.get("id"))
                        else:
                            # Write as informational history (race_observation), NOT
                            # an active calibration. LTHR is human-confirmed — the
                            # athlete promotes a value via `fit calibrate lthr`
                            # after the dashboard flags the suggestion. This keeps
                            # a single non-max or noisy race from silently shifting
                            # the whole zone model. (Backfilled the same way by
                            # calibration.backfill_race_lthr.)
                            already = conn.execute(
                                "SELECT 1 FROM calibration WHERE metric='lthr' "
                                "AND method='race_observation' AND source_activity_id=? LIMIT 1",
                                (enriched["id"],),
                            ).fetchone()
                            if not already:
                                conn.execute("""
                                    INSERT INTO calibration (metric, value, method,
                                        confidence, date, source_activity_id, notes, active, flags)
                                    VALUES ('lthr', ?, 'race_observation', 'low', ?, ?, ?, 0, '[]')
                                """, (candidate_lthr, cal_date.isoformat(), enriched["id"],
                                      f"Race estimate from {enriched.get('name')} "
                                      f"({enriched.get('distance_km', '?')}km)"))
                                conn.commit()
                                logger.info("LTHR race estimate recorded (history) from %s: %d bpm",
                                            enriched.get("name"), candidate_lthr)
            progress.advance(task_a)
        counts["activities"] = len(activities)

        # Auto-update VO2max calibration from latest activity
        latest_vo2 = conn.execute(
            "SELECT date, vo2max FROM activities WHERE vo2max IS NOT NULL ORDER BY date DESC LIMIT 1"
        ).fetchone()
        if latest_vo2 and latest_vo2["vo2max"]:
            from fit.calibration import add_calibration
            existing_cal = get_active_calibration(conn, "vo2max")
            if not existing_cal or existing_cal["value"] != latest_vo2["vo2max"]:
                add_calibration(conn, "vo2max", latest_vo2["vo2max"],
                                "device_vo2max", "medium",
                                date.fromisoformat(latest_vo2["date"]))

        # 3c. AeT auto-derive — walk recent running activities ≥12 km that have
        # per-km splits and look like steady-pace efforts. Each qualifying run
        # produces an AeT calibration row (direct estimate, lower bound, or
        # upper bound depending on HR drift %). See extract_aet_from_steady_run.
        #
        # `prior_aet` is the pre-sync active row (loaded once at the top of
        # run_sync as `aet_cal`). Reusing it instead of re-querying per
        # iteration mirrors how max_hr / lthr extraction already works — and
        # makes the flag computation deterministic within a single sync run.
        aet_candidates = conn.execute(f"""
            SELECT id, date, name, type, distance_km, avg_hr, run_type
            FROM activities
            WHERE date BETWEEN ? AND ?
              AND type IN {RUNNING_TYPES_SQL}
              AND distance_km >= 12
        """, (start.isoformat(), end.isoformat())).fetchall()
        for a in aet_candidates:
            splits = conn.execute(
                "SELECT split_num, distance_km, pace_sec_per_km, avg_hr "
                "FROM activity_splits WHERE activity_id = ? ORDER BY split_num",
                (a["id"],),
            ).fetchall()
            if not splits:
                continue
            result = extract_aet_from_steady_run(dict(a), [dict(s) for s in splits])
            if not result:
                continue
            try:
                cal_date = date.fromisoformat(a["date"])
            except (ValueError, TypeError):
                continue
            classification = result["classification"]
            bound_flag = ["lower_bound"] if classification == "lower_bound" \
                else ["upper_bound"] if classification == "upper_bound" else []
            flags = sorted(set(derive_flags("aet", result["value"], "drift_test", aet_cal) + bound_flag))
            confidence = derive_confidence("drift_test", flags)
            add_calibration(
                conn, "aet", result["value"], "drift_test", confidence,
                cal_date,
                source_activity_id=a["id"],
                notes=(f"drift {result['drift_pct']}% ({classification}) "
                       f"from {a['name'] or '?'} ({a['distance_km']}km)"),
                flags=flags,
            )

        # 3b. RPE/feel/compliance from Garmin activity detail (running activities only).
        # Refresh policy: re-fetch activities ≤14 days old; fill-NULL beyond.
        running_in_window = conn.execute(
            f"SELECT id, date, rpe, feel, compliance_score FROM activities "
            f"WHERE date BETWEEN ? AND ? AND type IN {RUNNING_TYPES_SQL}",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
        recent_cutoff = (date.today() - timedelta(days=14)).isoformat()
        candidates = [
            r for r in running_in_window
            if r["date"] >= recent_cutoff
            or r["rpe"] is None or r["feel"] is None or r["compliance_score"] is None
        ]
        if candidates:
            task_rpe = progress.add_task("RPE detail", total=len(candidates))
            for r in candidates:
                try:
                    g = garmin.fetch_activity_rpe(api, r["id"])
                except Exception as e:
                    logger.debug("RPE fetch failed for %s: %s", r["id"], e)
                    progress.advance(task_rpe)
                    continue
                # Recent: overwrite when Garmin has values; otherwise preserve.
                # Old: fill only NULL fields.
                if r["date"] >= recent_cutoff:
                    conn.execute(
                        "UPDATE activities SET "
                        "rpe = COALESCE(?, rpe), "
                        "feel = COALESCE(?, feel), "
                        "compliance_score = COALESCE(?, compliance_score) "
                        "WHERE id = ?",
                        (g["rpe"], g["feel"], g["compliance_score"], r["id"]),
                    )
                else:
                    conn.execute(
                        "UPDATE activities SET "
                        "rpe = COALESCE(rpe, ?), "
                        "feel = COALESCE(feel, ?), "
                        "compliance_score = COALESCE(compliance_score, ?) "
                        "WHERE id = ?",
                        (g["rpe"], g["feel"], g["compliance_score"], r["id"]),
                    )
                progress.advance(task_rpe)
            conn.commit()

        # 4. SpO2
        task_s = progress.add_task("SpO2", total=total_days)
        spo2_data = garmin.fetch_spo2(api, start, end)
        for d_str, avg_spo2 in spo2_data.items():
            if avg_spo2 is not None:
                conn.execute("UPDATE daily_health SET avg_spo2 = ? WHERE date = ?", (avg_spo2, d_str))
                counts["spo2"] += 1
            progress.advance(task_s)

        # 5. Weather
        lat = config.get("profile", {}).get("location", {}).get("lat")
        lon = config.get("profile", {}).get("location", {}).get("lon")
        if lat and lon:
            activity_dates = {a["date"] for a in activities if a.get("date")}
            task_w = progress.add_task("Weather", total=len(activity_dates) + len(activities))
            for d_str in activity_dates:
                existing = conn.execute("SELECT 1 FROM weather WHERE date = ?", (d_str,)).fetchone()
                if not existing or full:
                    d = date.fromisoformat(d_str)
                    w = weather.fetch_daily_weather(d, float(lat), float(lon))
                    if w:
                        _upsert_weather(conn, w)
                        counts["weather"] += 1
                progress.advance(task_w)

            for a in activities:
                if a.get("start_lat") and a.get("start_lon") and a.get("date"):
                    existing_hw = conn.execute(
                        "SELECT temp_at_start_c FROM activities WHERE id = ? AND temp_at_start_c IS NOT NULL",
                        (a["id"],)
                    ).fetchone()
                    if not existing_hw or full:
                        try:
                            d = date.fromisoformat(a["date"])
                            hour = a.get("start_hour") or 8
                            hw = weather.fetch_hourly_weather(d, hour, float(a["start_lat"]), float(a["start_lon"]))
                            if hw:
                                conn.execute(
                                    "UPDATE activities SET temp_at_start_c = ?, humidity_at_start_pct = ? WHERE id = ?",
                                    (hw["temp_at_start_c"], hw["humidity_at_start_pct"], a["id"]),
                                )
                        except Exception as e:
                            logger.debug("Hourly weather failed for %s: %s", a["id"], e)
                progress.advance(task_w)

        # 6. Weekly aggregation
        affected_weeks = _get_affected_weeks(activities, start, end)
        task_wk = progress.add_task("Weekly Agg", total=len(affected_weeks))
        for week_str in affected_weeks:
            agg = compute_weekly_agg(conn, week_str)
            _upsert_weekly_agg(conn, agg)
            counts["weekly_agg"] += 1
            progress.advance(task_wk)

    conn.commit()

    # 7. Match activities to race calendar
    _match_race_calendar(conn)

    # 8. Body comp staleness check. The actual import is the manual
    # `fit import-health <Export.zip>` workflow — parsing the ~1 GB XML on
    # every sync would dominate run time, and Apple Health exports are
    # user-initiated anyway. Here we just warn if body_comp is falling behind.
    last_bc = conn.execute(
        "SELECT MAX(date) FROM body_comp WHERE weight_kg IS NOT NULL"
    ).fetchone()[0]
    if last_bc:
        days_old = (date.today() - date.fromisoformat(last_bc)).days
        if days_old < 0:
            # Future-dated body_comp row — typo or bad import. Surface it loudly:
            # the row is "fresh" by the > 14 check but the data is bogus.
            warnings.append(
                f"Body comp has a future-dated row (last {last_bc}). "
                f"Check the source — manual entry typo or bad timezone in an Apple Health import."
            )
        elif days_old > 14:
            warnings.append(
                f"Body comp is {days_old} days old (last {last_bc}). "
                f"Re-export Apple Health → Export.zip and run 'fit import-health ~/Downloads/Export.zip'."
            )
    else:
        warnings.append(
            "No body comp data. Run 'fit import-health ~/Downloads/Export.zip' "
            "after exporting from the Apple Health app, or enter weight via 'fit checkin'."
        )

    # 8a. Compute sRPE (retroactively join checkin RPE to same-day activities)
    try:
        from fit.analysis import compute_srpe
        srpe_count = compute_srpe(conn)
        if srpe_count:
            counts["srpe"] = srpe_count
    except Exception as e:
        logger.debug("sRPE computation skipped: %s", e)

    # 8a2. Record VDOT observations from races ∪ hard efforts (informational
    #      rows feeding the standardized anchor + calibration history). Idempotent.
    try:
        from fit.calibration import backfill_race_vdot, backfill_effort_vdot
        v = backfill_race_vdot(conn) + backfill_effort_vdot(conn)
        if v:
            counts["vdot_estimates"] = v
    except Exception as e:
        logger.debug("VDOT observation backfill skipped: %s", e)

    # 8a3. Anchors never change silently — surface any metric whose suggestion
    #      now differs from the confirmed value for the human to accept/reject.
    try:
        from fit.calibration import evaluate_suggestions
        pending = evaluate_suggestions(conn)
        if pending:
            counts["calibration_suggestions"] = len(pending)
            for p in pending:
                logger.info("Calibration suggestion: %s %s (active %s) — review with "
                            "`fit calibrate %s`", p["metric"], p["value"], p["active"], p["metric"])
    except Exception as e:
        logger.debug("Calibration suggestion check skipped: %s", e)

    # 8b. Sync planned workouts from Garmin Calendar (Runna)
    try:
        from fit.plan import sync_planned_workouts
        plan_count = sync_planned_workouts(api, conn)
        if plan_count:
            counts["planned_workouts"] = plan_count
    except Exception as e:
        logger.debug("Plan sync skipped: %s", e)

    # 8b2. Update plan statuses (active → completed/missed for past dates)
    try:
        from fit.plan import update_plan_statuses
        update_plan_statuses(conn)
    except Exception as e:
        logger.debug("Plan status update skipped: %s", e)

    # 8c. Auto-compute correlations + run alerts
    try:
        from fit.correlations import compute_all_correlations
        compute_all_correlations(conn)
    except Exception as e:
        logger.debug("Correlations skipped: %s", e)

    try:
        from fit.alerts import run_alerts
        alerts = run_alerts(conn, config)
        if alerts:
            counts["alerts"] = len(alerts)
    except Exception as e:
        logger.debug("Alerts skipped: %s", e)

    # 9. Fetch per-km splits from Garmin API for running activities
    try:
        running_ids = [a["id"] for a in activities
                       if a.get("type") in ("running", "track_running", "trail_running", "treadmill_running")]
        to_process = []
        for aid in running_ids:
            row = conn.execute(
                "SELECT splits_status FROM activities WHERE id = ?", (aid,)
            ).fetchone()
            if not row or row["splits_status"] != "done":
                to_process.append(aid)

        splits_count = 0
        for aid in to_process:
            splits = garmin.fetch_activity_splits(api, aid)
            if splits:
                _upsert_splits(conn, aid, splits)
                splits_count += 1
        if splits_count:
            counts["splits"] = splits_count
    except Exception as e:
        logger.debug("Splits fetch skipped: %s", e)

    # 9b. Backfill splits for older activities (if --splits or config enabled)
    should_backfill = download_splits or config.get("sync", {}).get("download_fit_files", False)
    if should_backfill:
        try:
            max_backfill = config.get("sync", {}).get("max_fit_downloads", 20)
            all_running = conn.execute(f"""
                SELECT id FROM activities
                WHERE type IN {RUNNING_TYPES_SQL}
                  AND (splits_status IS NULL OR splits_status != 'done')
                ORDER BY date DESC LIMIT ?
            """, (max_backfill,)).fetchall()
            backfill_count = 0
            for row in all_running:
                splits = garmin.fetch_activity_splits(api, row["id"])
                if splits:
                    _upsert_splits(conn, row["id"], splits)
                    backfill_count += 1
            if backfill_count:
                counts["splits_backfill"] = backfill_count
        except Exception as e:
            logger.debug("Splits backfill skipped: %s", e)

    # Refit the marathon-durability posterior on fresh data (best-effort; never blocks a
    # sync). Skipped silently when the `forecast` extra is absent or there's no fittable
    # history — the dashboard degrades to the anchor headline (Decision 7).
    if _refit_marathon_forecast(conn):
        counts["forecast_refit"] = 1

    if warnings:
        counts["warnings"] = warnings
    logger.info("Sync complete: %s", counts)
    return counts


def _refit_marathon_forecast(conn: sqlite3.Connection) -> bool:
    """Refit + cache the marathon posterior. Returns True on success, False on any
    skip/failure (missing extra, no efforts, sampler error) — sync must never fail here."""
    try:
        from fit.marathon import model as _model
        from fit.marathon.features import extract_efforts
    except ImportError:
        return False
    try:
        ds = extract_efforts(conn)
    except ValueError:
        return False
    try:
        _model.fit(ds)  # samples + caches to ~/.fit/marathon_posterior.zarr
        logger.info("Marathon forecast posterior refit")
        return True
    except Exception as e:  # pragma: no cover - defensive (sampler/env issues)
        logger.warning("Marathon forecast refit skipped: %s", e)
        return False


def _match_race_calendar(conn: sqlite3.Connection) -> None:
    """Match race_calendar entries to activities by date. Tag matched activities as run_type='race'.

    Auto-completes 'registered' races whose date has passed when a matching activity exists.
    When multiple activities exist on race day, picks the one closest in distance to the race.
    """
    from datetime import date as _date

    # Auto-complete registered races whose date has passed (or is today) and an
    # activity exists. `<=` (not `<`) so a race run and synced on the SAME day
    # matches immediately — the activity only exists once you've run, so a
    # same-day match implies the race happened.
    past_registered = conn.execute("""
        SELECT rc.id, rc.date, rc.distance_km FROM race_calendar rc
        WHERE rc.status = 'registered' AND rc.date <= ?
    """, (_date.today().isoformat(),)).fetchall()
    for rc in past_registered:
        activities = conn.execute(f"""
            SELECT id, distance_km FROM activities
            WHERE date = ? AND type IN {RUNNING_TYPES_SQL}
        """, (rc["date"],)).fetchall()
        if activities:
            conn.execute("UPDATE race_calendar SET status = 'completed' WHERE id = ?", (rc["id"],))
            logger.info("Auto-completed race %s on %s (activity found)", rc["id"], rc["date"])

    # Match completed races without activity_id
    unmatched = conn.execute("""
        SELECT rc.id, rc.date, rc.distance_km FROM race_calendar rc
        WHERE rc.status = 'completed' AND rc.activity_id IS NULL
    """).fetchall()
    for rc in unmatched:
        activities = conn.execute(f"""
            SELECT id, distance_km, duration_min FROM activities
            WHERE date = ? AND type IN {RUNNING_TYPES_SQL}
        """, (rc["date"],)).fetchall()
        if activities:
            # Pick closest distance to race distance
            race_km = rc["distance_km"] or 0
            if race_km:
                activity = min(activities, key=lambda a: abs((a["distance_km"] or 0) - race_km))
            else:
                activity = max(activities, key=lambda a: a["distance_km"] or 0)
            dur = activity["duration_min"] or 0
            garmin_time = f"{int(dur // 60)}:{int(dur % 60):02d}:{int((dur * 60) % 60):02d}"
            pace = (dur * 60) / activity["distance_km"] if activity["distance_km"] else None
            conn.execute("""UPDATE race_calendar SET activity_id = ?, garmin_time = ?, result_pace = ?
                            WHERE id = ?""",
                         (activity["id"], garmin_time, pace, rc["id"]))
            conn.execute("UPDATE activities SET run_type = 'race' WHERE id = ?", (activity["id"],))
            logger.info("Race matched: %s → activity %s", rc["date"], activity["id"])

    # Self-heal: every completed race with a linked activity must be tagged
    # run_type='race'. The loop above only covers activity_id IS NULL, so a
    # race whose tag a past re-enrichment stripped (classify_run_type never
    # reproduces 'race') would otherwise stay mislabeled forever — it counts
    # as easy/tempo/long in every stat and never feeds race calibration.
    conn.execute("""
        UPDATE activities SET run_type = 'race'
        WHERE id IN (
            SELECT activity_id FROM race_calendar
            WHERE status = 'completed' AND activity_id IS NOT NULL
        ) AND (run_type IS NULL OR run_type != 'race')
    """)
    conn.commit()


def enrich_existing_activities(conn: sqlite3.Connection, config: dict,
                                force: bool = False) -> int:
    """Re-enrich activities with the current calibration.

    Default (`force=False`) only re-enriches rows missing `hr_zone` — used
    after sync to fill in any gaps. `force=True` re-enriches every activity.

    POINT-IN-TIME: each activity is classified with the calibration that was
    active AS OF ITS OWN DATE (get_active_calibration(..., asof=activity_date)),
    NOT today's value. So changing an anchor (e.g. confirming a new LTHR) does
    NOT retroactively reclassify past activities or shift past weekly/phase
    aggregates — history stays as it was reasoned at the time, and the
    `lthr_used`/`max_hr_used` stamp + the dated calibration rows reconstruct why.
    Re-enriching is therefore idempotent across later anchor changes.

    Returns count of enriched activities.
    """
    cfg_max_hr = config["profile"].get("max_hr")
    # Resolve the as-of anchor per activity date, cached by date (calibration
    # changes are rare, activities cluster on few dates).
    _asof_cache: dict[str, tuple] = {}

    def _anchors_asof(day: str):
        if day not in _asof_cache:
            try:
                ref = date.fromisoformat(day)
            except (ValueError, TypeError):
                ref = None
            lc = get_active_calibration(conn, "lthr", asof=ref)
            mc = get_active_calibration(conn, "max_hr", asof=ref)
            ac = get_active_calibration(conn, "aet", asof=ref)
            _asof_cache[day] = (
                int(lc["value"]) if lc else None,
                int(mc["value"]) if mc else cfg_max_hr,
                int(ac["value"]) if ac else None,
            )
        return _asof_cache[day]

    where_clause = "" if force else "WHERE hr_zone IS NULL"
    # `run_type` is included so `enrich_activity` can preserve existing 'race'
    # tags — they're written by `_match_race_calendar` (a separate sync stage)
    # and classify_run_type never reproduces them.
    rows = conn.execute(f"""
        SELECT id, date, type, subtype, name, distance_km, duration_min,
               pace_sec_per_km, avg_hr, max_hr, avg_cadence, elevation_gain_m,
               calories, vo2max, aerobic_te, training_load, avg_stride_m,
               avg_speed, start_lat, start_lon, run_type
        FROM activities {where_clause}
    """).fetchall()

    count = 0
    for row in rows:
        a = dict(row)
        lthr, max_hr, aet = _anchors_asof(a["date"])
        enriched = enrich_activity(a, config, lthr=lthr, max_hr=max_hr, aet=aet)
        conn.execute("""
            UPDATE activities SET
                hr_zone_maxhr = ?, hr_zone_lthr = ?, hr_zone = ?,
                effort_class = ?, speed_per_bpm = ?, speed_per_bpm_z2 = ?,
                run_type = ?, max_hr_used = ?, lthr_used = ?
            WHERE id = ?
        """, (
            enriched.get("hr_zone_maxhr"), enriched.get("hr_zone_lthr"),
            enriched.get("hr_zone"), enriched.get("effort_class"),
            enriched.get("speed_per_bpm"), enriched.get("speed_per_bpm_z2"),
            enriched.get("run_type"), enriched.get("max_hr_used"),
            enriched.get("lthr_used"), enriched["id"],
        ))
        count += 1

    conn.commit()
    logger.info("Enriched %d existing activities", count)
    return count


def _upsert_health(conn: sqlite3.Connection, h: dict) -> None:
    """Upsert a daily health row using INSERT ON CONFLICT."""
    conn.execute("""
        INSERT INTO daily_health (
            date, total_steps, total_distance_m, total_calories, active_calories,
            resting_heart_rate, max_heart_rate, min_heart_rate,
            avg_stress_level, max_stress_level, body_battery_high, body_battery_low,
            sleep_duration_hours, deep_sleep_hours, light_sleep_hours,
            rem_sleep_hours, awake_hours, deep_sleep_pct,
            training_readiness, readiness_level,
            hrv_weekly_avg, hrv_last_night, hrv_status,
            avg_respiration, avg_spo2
        ) VALUES (
            :date, :total_steps, :total_distance_m, :total_calories, :active_calories,
            :resting_heart_rate, :max_heart_rate, :min_heart_rate,
            :avg_stress_level, :max_stress_level, :body_battery_high, :body_battery_low,
            :sleep_duration_hours, :deep_sleep_hours, :light_sleep_hours,
            :rem_sleep_hours, :awake_hours, :deep_sleep_pct,
            :training_readiness, :readiness_level,
            :hrv_weekly_avg, :hrv_last_night, :hrv_status,
            :avg_respiration, :avg_spo2
        )
        ON CONFLICT(date) DO UPDATE SET
            total_steps = excluded.total_steps,
            total_distance_m = excluded.total_distance_m,
            total_calories = excluded.total_calories,
            active_calories = excluded.active_calories,
            resting_heart_rate = excluded.resting_heart_rate,
            max_heart_rate = excluded.max_heart_rate,
            min_heart_rate = excluded.min_heart_rate,
            avg_stress_level = excluded.avg_stress_level,
            max_stress_level = excluded.max_stress_level,
            body_battery_high = excluded.body_battery_high,
            body_battery_low = excluded.body_battery_low,
            sleep_duration_hours = excluded.sleep_duration_hours,
            deep_sleep_hours = excluded.deep_sleep_hours,
            light_sleep_hours = excluded.light_sleep_hours,
            rem_sleep_hours = excluded.rem_sleep_hours,
            awake_hours = excluded.awake_hours,
            deep_sleep_pct = excluded.deep_sleep_pct,
            training_readiness = excluded.training_readiness,
            readiness_level = excluded.readiness_level,
            hrv_weekly_avg = excluded.hrv_weekly_avg,
            hrv_last_night = excluded.hrv_last_night,
            hrv_status = excluded.hrv_status,
            avg_respiration = excluded.avg_respiration,
            avg_spo2 = COALESCE(excluded.avg_spo2, daily_health.avg_spo2)
    """, {
        "date": h.get("date"),
        "total_steps": h.get("total_steps"),
        "total_distance_m": h.get("total_distance_m"),
        "total_calories": h.get("total_calories"),
        "active_calories": h.get("active_calories"),
        "resting_heart_rate": h.get("resting_heart_rate"),
        "max_heart_rate": h.get("max_heart_rate"),
        "min_heart_rate": h.get("min_heart_rate"),
        "avg_stress_level": h.get("avg_stress_level"),
        "max_stress_level": h.get("max_stress_level"),
        "body_battery_high": h.get("body_battery_high"),
        "body_battery_low": h.get("body_battery_low"),
        "sleep_duration_hours": h.get("sleep_duration_hours"),
        "deep_sleep_hours": h.get("deep_sleep_hours"),
        "light_sleep_hours": h.get("light_sleep_hours"),
        "rem_sleep_hours": h.get("rem_sleep_hours"),
        "awake_hours": h.get("awake_hours"),
        "deep_sleep_pct": h.get("deep_sleep_pct"),
        "training_readiness": h.get("training_readiness"),
        "readiness_level": h.get("readiness_level"),
        "hrv_weekly_avg": h.get("hrv_weekly_avg"),
        "hrv_last_night": h.get("hrv_last_night"),
        "hrv_status": h.get("hrv_status"),
        "avg_respiration": h.get("avg_respiration"),
        "avg_spo2": h.get("avg_spo2"),
    })


def _upsert_activity(conn: sqlite3.Connection, a: dict) -> None:
    """Upsert an activity. Only raw Garmin fields updated on conflict — derived metrics preserved."""
    conn.execute("""
        INSERT INTO activities (
            id, date, type, subtype, name,
            distance_km, duration_min, pace_sec_per_km,
            avg_hr, max_hr, avg_cadence, elevation_gain_m,
            calories, vo2max, aerobic_te, training_load,
            avg_stride_m, avg_speed, start_lat, start_lon
        ) VALUES (
            :id, :date, :type, :subtype, :name,
            :distance_km, :duration_min, :pace_sec_per_km,
            :avg_hr, :max_hr, :avg_cadence, :elevation_gain_m,
            :calories, :vo2max, :aerobic_te, :training_load,
            :avg_stride_m, :avg_speed, :start_lat, :start_lon
        )
        ON CONFLICT(id) DO UPDATE SET
            date = excluded.date,
            type = excluded.type,
            name = excluded.name,
            distance_km = excluded.distance_km,
            duration_min = excluded.duration_min,
            pace_sec_per_km = excluded.pace_sec_per_km,
            avg_hr = excluded.avg_hr,
            max_hr = excluded.max_hr,
            avg_cadence = excluded.avg_cadence,
            elevation_gain_m = excluded.elevation_gain_m,
            calories = excluded.calories,
            vo2max = excluded.vo2max,
            aerobic_te = excluded.aerobic_te,
            training_load = excluded.training_load,
            avg_stride_m = excluded.avg_stride_m,
            avg_speed = excluded.avg_speed,
            start_lat = excluded.start_lat,
            start_lon = excluded.start_lon
    """, a)


def _upsert_enriched_activity(conn: sqlite3.Connection, a: dict) -> None:
    """Insert a new enriched activity with all derived fields."""
    conn.execute("""
        INSERT INTO activities (
            id, date, type, subtype, name,
            distance_km, duration_min, pace_sec_per_km,
            avg_hr, max_hr, avg_cadence, elevation_gain_m,
            calories, vo2max, aerobic_te, training_load,
            avg_stride_m, avg_speed, start_lat, start_lon,
            hr_zone_maxhr, hr_zone_lthr, hr_zone,
            speed_per_bpm, speed_per_bpm_z2,
            effort_class, run_type, max_hr_used, lthr_used
        ) VALUES (
            :id, :date, :type, :subtype, :name,
            :distance_km, :duration_min, :pace_sec_per_km,
            :avg_hr, :max_hr, :avg_cadence, :elevation_gain_m,
            :calories, :vo2max, :aerobic_te, :training_load,
            :avg_stride_m, :avg_speed, :start_lat, :start_lon,
            :hr_zone_maxhr, :hr_zone_lthr, :hr_zone,
            :speed_per_bpm, :speed_per_bpm_z2,
            :effort_class, :run_type, :max_hr_used, :lthr_used
        )
        ON CONFLICT(id) DO UPDATE SET
            date = excluded.date, type = excluded.type, name = excluded.name,
            distance_km = excluded.distance_km, duration_min = excluded.duration_min,
            pace_sec_per_km = excluded.pace_sec_per_km,
            avg_hr = excluded.avg_hr, max_hr = excluded.max_hr,
            avg_cadence = excluded.avg_cadence, elevation_gain_m = excluded.elevation_gain_m,
            calories = excluded.calories, vo2max = excluded.vo2max,
            aerobic_te = excluded.aerobic_te, training_load = excluded.training_load,
            avg_stride_m = excluded.avg_stride_m, avg_speed = excluded.avg_speed,
            start_lat = excluded.start_lat, start_lon = excluded.start_lon
    """, a)


def _upsert_weekly_agg(conn: sqlite3.Connection, agg: dict) -> None:
    """Upsert a weekly_agg row."""
    cols = list(agg.keys())
    placeholders = ", ".join(f":{c}" for c in cols)
    updates = ", ".join(f"{c} = excluded.{c}" for c in cols if c != "week")
    conn.execute(f"""
        INSERT INTO weekly_agg ({', '.join(cols)})
        VALUES ({placeholders})
        ON CONFLICT(week) DO UPDATE SET {updates}
    """, agg)


def _get_affected_weeks(activities: list[dict], start: date, end: date) -> set[str]:
    """Get ISO week strings for all dates in the sync range."""
    weeks = set()
    current = start
    while current <= end:
        iso = current.isocalendar()
        weeks.add(f"{iso.year}-W{iso.week:02d}")
        current += timedelta(days=1)
    return weeks


def _upsert_splits(conn: sqlite3.Connection, activity_id: str, splits: list[dict]) -> None:
    """Upsert per-km splits from the Garmin API and mark the activity as done."""
    for s in splits:
        conn.execute("""
            INSERT INTO activity_splits
                (activity_id, split_num, distance_km, time_sec, pace_sec_per_km,
                 avg_hr, max_hr, avg_cadence, elevation_gain_m, elevation_loss_m,
                 avg_speed_m_s, intensity_type, wkt_step_index)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(activity_id, split_num) DO UPDATE SET
                pace_sec_per_km = excluded.pace_sec_per_km,
                avg_hr = excluded.avg_hr,
                max_hr = excluded.max_hr,
                avg_cadence = excluded.avg_cadence,
                elevation_gain_m = excluded.elevation_gain_m,
                elevation_loss_m = excluded.elevation_loss_m,
                avg_speed_m_s = excluded.avg_speed_m_s,
                intensity_type = excluded.intensity_type,
                wkt_step_index = excluded.wkt_step_index
        """, (activity_id, s["split_num"], s["distance_km"], s["time_sec"],
              s["pace_sec_per_km"], s.get("avg_hr"), s.get("max_hr"),
              s.get("avg_cadence"), s.get("elevation_gain_m"),
              s.get("elevation_loss_m"), s.get("avg_speed_m_s"),
              s.get("intensity_type"), s.get("wkt_step_index")))
    conn.execute(
        "UPDATE activities SET splits_status = 'done' WHERE id = ?", (activity_id,)
    )
    conn.commit()


def _upsert_weather(conn: sqlite3.Connection, w: dict) -> None:
    """Upsert a daily weather row."""
    conn.execute("""
        INSERT INTO weather (date, temp_c, temp_max_c, temp_min_c, humidity_pct,
                             wind_speed_kmh, precipitation_mm, conditions)
        VALUES (:date, :temp_c, :temp_max_c, :temp_min_c, :humidity_pct,
                :wind_speed_kmh, :precipitation_mm, :conditions)
        ON CONFLICT(date) DO UPDATE SET
            temp_c = excluded.temp_c,
            temp_max_c = excluded.temp_max_c,
            temp_min_c = excluded.temp_min_c,
            humidity_pct = excluded.humidity_pct,
            wind_speed_kmh = excluded.wind_speed_kmh,
            precipitation_mm = excluded.precipitation_mm,
            conditions = excluded.conditions
    """, w)
