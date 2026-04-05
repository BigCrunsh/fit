"""Cross-domain correlation analysis using Spearman rank correlation."""

import logging
import math
import sqlite3

logger = logging.getLogger(__name__)

# Predefined correlation pairs: (name, query_x, query_y, lag_days, min_n_report, min_n_coaching)
CORRELATION_PAIRS = [
    ("alcohol→HRV (lag 1)", "alcohol_lag1_hrv", 1, 20, 30,
     "SELECT c.date, c.alcohol as x FROM checkins c WHERE c.alcohol IS NOT NULL",
     "SELECT h.date, h.hrv_last_night as y FROM daily_health h WHERE h.hrv_last_night IS NOT NULL"),
    ("alcohol→RHR (lag 1)", "alcohol_lag1_rhr", 1, 20, 30,
     "SELECT c.date, c.alcohol as x FROM checkins c WHERE c.alcohol IS NOT NULL",
     "SELECT h.date, h.resting_heart_rate as y FROM daily_health h WHERE h.resting_heart_rate IS NOT NULL"),
    ("sleep quality→readiness", "sleep_quality_readiness", 0, 20, 30,
     "SELECT c.date, CASE c.sleep_quality WHEN 'Poor' THEN 1 WHEN 'OK' THEN 2 WHEN 'Good' THEN 3 ELSE NULL END as x FROM checkins c WHERE c.sleep_quality IS NOT NULL",
     "SELECT h.date, h.training_readiness as y FROM daily_health h WHERE h.training_readiness IS NOT NULL"),
    ("temp→efficiency", "temp_speed_per_bpm", 0, 20, 30,
     "SELECT a.date, a.temp_at_start_c as x FROM activities a WHERE a.temp_at_start_c IS NOT NULL AND a.type='running'",
     "SELECT a.date, a.speed_per_bpm as y FROM activities a WHERE a.speed_per_bpm IS NOT NULL AND a.type='running'"),
    ("water→HRV (lag 1)", "water_lag1_hrv", 1, 20, 30,
     "SELECT c.date, c.water_liters as x FROM checkins c WHERE c.water_liters IS NOT NULL",
     "SELECT h.date, h.hrv_last_night as y FROM daily_health h WHERE h.hrv_last_night IS NOT NULL"),
]


def compute_all_correlations(conn: sqlite3.Connection) -> list[dict]:
    """Compute all predefined correlation pairs. Returns list of results."""
    results = []
    for name, metric_pair, lag, min_report, min_coaching, sql_x, sql_y in CORRELATION_PAIRS:
        # Check if data count changed since last compute
        existing = conn.execute("SELECT data_count_at_compute FROM correlations WHERE metric_pair = ?", (metric_pair,)).fetchone()

        x_rows = conn.execute(sql_x).fetchall()
        y_rows = conn.execute(sql_y).fetchall()

        if existing and existing["data_count_at_compute"] == len(x_rows) + len(y_rows):
            logger.debug("Skipping %s — data unchanged", metric_pair)
            continue

        # Build paired data with lag
        x_dict = {r["date"]: r["x"] for r in x_rows}
        y_dict = {r["date"]: r["y"] for r in y_rows}

        pairs = []
        for d, xv in x_dict.items():
            if lag > 0:
                from datetime import date, timedelta
                try:
                    target_date = (date.fromisoformat(d) + timedelta(days=lag)).isoformat()
                except (ValueError, TypeError):
                    continue
            else:
                target_date = d
            if target_date in y_dict and xv is not None and y_dict[target_date] is not None:
                pairs.append((float(xv), float(y_dict[target_date])))

        n = len(pairs)
        if n < min_report:
            result = {
                "metric_pair": metric_pair, "lag_days": lag, "spearman_r": None, "pearson_r": None,
                "p_value": None, "sample_size": n, "confidence": "low",
                "status": "insufficient_data", "data_count_at_compute": len(x_rows) + len(y_rows),
            }
        else:
            xs = [p[0] for p in pairs]
            ys = [p[1] for p in pairs]
            sr = _spearman_r(xs, ys)
            pr = _pearson_r(xs, ys)
            pval = _p_value(sr, n) if sr is not None else None
            confidence = "high" if n >= 30 and pval and pval < 0.05 else "moderate" if n >= min_report else "low"
            result = {
                "metric_pair": metric_pair, "lag_days": lag, "spearman_r": round(sr, 4) if sr else None,
                "pearson_r": round(pr, 4) if pr else None, "p_value": round(pval, 4) if pval else None,
                "sample_size": n, "confidence": confidence,
                "status": "computed", "data_count_at_compute": len(x_rows) + len(y_rows),
            }

        # Upsert
        conn.execute("""
            INSERT INTO correlations (metric_pair, lag_days, spearman_r, pearson_r, p_value,
                                      sample_size, confidence, status, last_computed, data_count_at_compute)
            VALUES (:metric_pair, :lag_days, :spearman_r, :pearson_r, :p_value,
                    :sample_size, :confidence, :status, datetime('now'), :data_count_at_compute)
            ON CONFLICT(metric_pair) DO UPDATE SET
                spearman_r = excluded.spearman_r, pearson_r = excluded.pearson_r,
                p_value = excluded.p_value, sample_size = excluded.sample_size,
                confidence = excluded.confidence, status = excluded.status,
                last_computed = excluded.last_computed, data_count_at_compute = excluded.data_count_at_compute
        """, result)
        results.append({**result, "name": name})
        logger.info("Correlation %s: r=%.3f, n=%d, %s", name, result.get("spearman_r") or 0, n, result["status"])

    conn.commit()
    return results


def _rank(values: list[float]) -> list[float]:
    """Assign ranks to values (handles ties with average rank)."""
    indexed = sorted(enumerate(values), key=lambda x: x[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i
        while j < len(indexed) - 1 and indexed[j + 1][1] == indexed[j][1]:
            j += 1
        avg_rank = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[indexed[k][0]] = avg_rank
        i = j + 1
    return ranks


def _spearman_r(xs: list[float], ys: list[float]) -> float | None:
    """Compute Spearman rank correlation via rank transform."""
    if len(xs) < 3:
        return None
    rx = _rank(xs)
    ry = _rank(ys)
    return _pearson_r(rx, ry)


def _pearson_r(xs: list[float], ys: list[float]) -> float | None:
    """Compute Pearson correlation coefficient."""
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return None
    return cov / (sx * sy)


def _p_value(r: float, n: int) -> float | None:
    """Compute p-value for correlation via t-distribution approximation."""
    if n < 4 or r is None or abs(r) >= 1.0:
        return None
    t = r * math.sqrt((n - 2) / (1 - r * r))
    # Approximate two-tailed p-value using normal CDF (good for n > 30)
    p = 2 * (1 - _norm_cdf(abs(t)))
    return max(p, 1e-10)


def _norm_cdf(x: float) -> float:
    """Standard normal CDF approximation."""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))
