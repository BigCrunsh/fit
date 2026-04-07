"""Apple Health XML export importer — streaming parser for body comp + supplementary data."""

import logging
import sqlite3
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile

logger = logging.getLogger(__name__)

# Records we care about (type → our field name)
RECORD_TYPES = {
    "HKQuantityTypeIdentifierBodyMass": "weight_kg",
    "HKQuantityTypeIdentifierBodyFatPercentage": "body_fat_pct",
    "HKQuantityTypeIdentifierLeanBodyMass": "lean_body_mass_kg",
    "HKQuantityTypeIdentifierBodyMassIndex": "bmi",
}


def import_apple_health(conn: sqlite3.Connection, export_path: Path) -> dict:
    """Import body composition data from Apple Health export.

    Args:
        conn: SQLite connection.
        export_path: Path to Export.zip or Export.xml.

    Returns:
        Dict with counts per record type imported.
    """
    export_path = Path(export_path).expanduser()
    if not export_path.exists():
        logger.warning("Apple Health export not found at %s", export_path)
        return {"error": f"File not found: {export_path}"}

    # Handle ZIP or raw XML
    if export_path.suffix == ".zip":
        xml_path = _extract_xml_from_zip(export_path)
        if not xml_path:
            return {"error": "No Export.xml found in ZIP"}
    else:
        xml_path = export_path

    logger.info("Parsing Apple Health export: %s", xml_path)

    # Collect records by date for body comp
    body_comp = {}  # date_str → {weight_kg, body_fat_pct, lean_body_mass_kg, bmi}
    counts = {v: 0 for v in RECORD_TYPES.values()}

    # Stream-parse the XML (it's huge — don't load into memory)
    for event, elem in ET.iterparse(str(xml_path), events=("end",)):
        if elem.tag != "Record":
            elem.clear()
            continue

        record_type = elem.get("type", "")
        if record_type not in RECORD_TYPES:
            elem.clear()
            continue

        field = RECORD_TYPES[record_type]
        value_str = elem.get("value")
        start_date = elem.get("startDate", "")

        if not value_str or not start_date:
            elem.clear()
            continue

        try:
            value = float(value_str)
        except ValueError:
            elem.clear()
            continue

        # Parse date (format: "2023-01-21 09:26:18 +0200")
        date_str = start_date[:10]

        # Convert units: body fat comes as 0.169 (fraction), we store as 16.9%
        if field == "body_fat_pct" and value < 1.0:
            value = round(value * 100, 1)

        # Group by date — keep latest reading per day
        if date_str not in body_comp:
            body_comp[date_str] = {}
        body_comp[date_str][field] = value
        counts[field] += 1

        elem.clear()

    # Upsert into body_comp table
    imported = 0
    for date_str, data in sorted(body_comp.items()):
        weight = data.get("weight_kg")
        if not weight:
            continue

        conn.execute("""
            INSERT INTO body_comp (date, weight_kg, body_fat_pct, muscle_mass_kg, bmi, source)
            VALUES (?, ?, ?, ?, ?, 'apple_health')
            ON CONFLICT(date) DO UPDATE SET
                weight_kg = COALESCE(excluded.weight_kg, body_comp.weight_kg),
                body_fat_pct = COALESCE(excluded.body_fat_pct, body_comp.body_fat_pct),
                muscle_mass_kg = COALESCE(excluded.muscle_mass_kg, body_comp.muscle_mass_kg),
                bmi = COALESCE(excluded.bmi, body_comp.bmi),
                source = 'apple_health'
        """, (
            date_str,
            weight,
            data.get("body_fat_pct"),
            data.get("lean_body_mass_kg"),
            data.get("bmi"),
        ))
        imported += 1

    # Auto-update weight calibration from latest body_comp
    if imported > 0:
        latest = conn.execute(
            "SELECT date, weight_kg FROM body_comp WHERE weight_kg IS NOT NULL ORDER BY date DESC LIMIT 1"
        ).fetchone()
        if latest:
            from fit.calibration import add_calibration
            from datetime import date
            add_calibration(conn, "weight", latest["weight_kg"], "scale", "high",
                            date.fromisoformat(latest["date"]))

    conn.commit()
    logger.info("Imported %d body comp records from Apple Health (%s)", imported, counts)

    return {"imported": imported, "records": counts, "date_range": (
        min(body_comp.keys()) if body_comp else None,
        max(body_comp.keys()) if body_comp else None,
    )}


def _extract_xml_from_zip(zip_path: Path) -> Path | None:
    """Extract Export.xml from Apple Health ZIP."""
    try:
        with ZipFile(zip_path) as zf:
            xml_names = [n for n in zf.namelist() if n.endswith("Export.xml")]
            if not xml_names:
                return None
            # Extract to same directory as ZIP
            target_dir = zip_path.parent
            zf.extract(xml_names[0], target_dir)
            return target_dir / xml_names[0]
    except Exception as e:
        logger.error("Failed to extract ZIP: %s", e)
        return None
