"""
Reads a day's worth of raw snapshots and normalizes them into two clean
tables:

  - trip_updates: one row per (trip_id, stop_id) predicted arrival/departure,
    deduped across overlapping polls (we poll every 30-60s, so the same
    trip/stop prediction shows up in many consecutive snapshots).
  - vehicle_positions: one row per (trip_id) latest known position.

Output: data/processed/date=YYYY-MM-DD/trip_updates.parquet
        data/processed/date=YYYY-MM-DD/vehicle_positions.parquet

Usage:
    python -m processing.parse_snapshots --date 2026-08-25
    python -m processing.parse_snapshots            # defaults to yesterday (UTC)
"""
import argparse
import ast
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("parse_snapshots")

RAW_DATA_DIR = Path(os.getenv("RAW_DATA_DIR", "data/raw"))
PROCESSED_DATA_DIR = Path(os.getenv("PROCESSED_DATA_DIR", "data/processed"))


def _safe_literal_eval(value):
    """Raw snapshots store nested protobuf fields as Python-repr strings
    (see storage/writer.py). Parse them back into dicts, tolerating
    None/empty gracefully - a single malformed row shouldn't kill the
    whole batch job."""
    if value is None or value == "" or value == "None":
        return None
    try:
        return ast.literal_eval(value)
    except (ValueError, SyntaxError):
        return None


def load_raw_snapshots(date: str) -> pd.DataFrame:
    """Load every raw snapshot file for a given date across all lines/hours."""
    date_dir = RAW_DATA_DIR / f"date={date}"
    if not date_dir.exists():
        log.warning("No raw data found for date=%s at %s", date, date_dir)
        return pd.DataFrame()

    con = duckdb.connect()
    # DuckDB glob reads every partition in one shot and gives us the
    # partition columns (line, hour) back for free.
    query = f"""
        SELECT *
        FROM read_parquet('{date_dir}/**/*.parquet', hive_partitioning=1)
    """
    df = con.execute(query).df()
    log.info("Loaded %s raw entity rows for date=%s", len(df), date)
    return df


def extract_trip_updates(raw_df: pd.DataFrame) -> pd.DataFrame:
    """Flatten trip_update.stop_time_update[] into one row per
    (trip_id, stop_id, predicted_time), keeping only the MOST RECENT
    prediction seen across all snapshots (later polls have fresher
    predictions for the same trip/stop)."""
    rows = []
    for _, raw_row in raw_df.iterrows():
        tu = _safe_literal_eval(raw_row.get("trip_update"))
        if not tu:
            continue

        trip = tu.get("trip", {})
        trip_id = trip.get("trip_id")
        route_id = trip.get("route_id")
        direction = trip.get("nyct_trip_descriptor", {}).get("direction") if isinstance(
            trip.get("nyct_trip_descriptor"), dict
        ) else None

        for stu in tu.get("stop_time_update", []):
            arrival = stu.get("arrival", {}).get("time")
            departure = stu.get("departure", {}).get("time")
            rows.append(
                {
                    "trip_id": trip_id,
                    "route_id": route_id,
                    "direction": direction,
                    "stop_id": stu.get("stop_id"),
                    "predicted_arrival": arrival,
                    "predicted_departure": departure,
                    "line": raw_row.get("line"),
                    "observed_at": raw_row.get("feed_timestamp"),
                }
            )

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df = df.dropna(subset=["trip_id", "stop_id"])

    # Dedup: keep the prediction with the LATEST observed_at for each
    # (trip_id, stop_id) pair - that's the freshest prediction we have.
    df["observed_at"] = pd.to_numeric(df["observed_at"], errors="coerce")
    df = df.sort_values("observed_at").drop_duplicates(
        subset=["trip_id", "stop_id"], keep="last"
    )
    return df.reset_index(drop=True)


def extract_vehicle_positions(raw_df: pd.DataFrame) -> pd.DataFrame:
    """Flatten vehicle position entities into one row per trip_id, keeping
    only the latest observed position."""
    rows = []
    for _, raw_row in raw_df.iterrows():
        veh = _safe_literal_eval(raw_row.get("vehicle"))
        if not veh:
            continue

        trip = veh.get("trip", {})
        rows.append(
            {
                "trip_id": trip.get("trip_id"),
                "route_id": trip.get("route_id"),
                "current_stop_id": veh.get("stop_id"),
                "current_status": veh.get("current_status"),
                "timestamp": veh.get("timestamp"),
                "line": raw_row.get("line"),
            }
        )

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df = df.dropna(subset=["trip_id"])
    df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce")
    df = df.sort_values("timestamp").drop_duplicates(subset=["trip_id"], keep="last")
    return df.reset_index(drop=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--date",
        type=str,
        default=(datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d"),
        help="Date to process, YYYY-MM-DD (default: yesterday UTC)",
    )
    args = parser.parse_args()

    raw_df = load_raw_snapshots(args.date)
    if raw_df.empty:
        log.warning("Nothing to process for %s", args.date)
        return

    trip_updates = extract_trip_updates(raw_df)
    vehicle_positions = extract_vehicle_positions(raw_df)

    out_dir = PROCESSED_DATA_DIR / f"date={args.date}"
    out_dir.mkdir(parents=True, exist_ok=True)

    if not trip_updates.empty:
        trip_updates.to_parquet(out_dir / "trip_updates.parquet", index=False)
        log.info("Wrote %s deduped trip_update rows", len(trip_updates))
    if not vehicle_positions.empty:
        vehicle_positions.to_parquet(out_dir / "vehicle_positions.parquet", index=False)
        log.info("Wrote %s deduped vehicle_position rows", len(vehicle_positions))


if __name__ == "__main__":
    main()
