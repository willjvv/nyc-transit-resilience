"""Normalize raw GTFS-realtime snapshots without destroying prediction history.

Outputs per service date:
  - trip_update_observations.parquet: every observed prediction
  - trip_updates.parquet: latest observation per (realtime trip, stop), retained
    as a convenient terminal-prediction table for daily metrics
  - vehicle_positions.parquet: latest observed vehicle position per trip

The realtime timestamp remains an absolute Unix timestamp. Derived local/service-day
fields are added only for analytical joins so that UTC and GTFS service-day semantics
are never conflated.
"""
from __future__ import annotations

import argparse
import ast
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb
import pandas as pd

from processing.time_utils import NY_TZ, local_date_from_unix, service_date_candidates

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("parse_snapshots")

RAW_DATA_DIR = Path(os.getenv("RAW_DATA_DIR", "data/raw"))
PROCESSED_DATA_DIR = Path(os.getenv("PROCESSED_DATA_DIR", "data/processed"))


def _safe_mapping(value):
    if value is None or value == "" or value == "None":
        return None
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        try:
            return ast.literal_eval(value)
        except (ValueError, SyntaxError):
            return None


def _raw_dates_for_service_date(service_date: str) -> list[str]:
    """Load UTC partitions spanning the requested New York service date."""
    d = datetime.strptime(service_date, "%Y-%m-%d").date()
    # A service day can extend past local midnight, so include the next UTC day.
    return [d.isoformat(), (d + timedelta(days=1)).isoformat()]


def load_raw_snapshots(service_date: str) -> pd.DataFrame:
    paths = []
    for utc_date in _raw_dates_for_service_date(service_date):
        date_dir = RAW_DATA_DIR / f"date={utc_date}"
        if date_dir.exists():
            paths.append(date_dir)

    if not paths:
        log.warning("No raw data found spanning service date=%s at %s", service_date, RAW_DATA_DIR)
        return pd.DataFrame()

    con = duckdb.connect()
    globs = ", ".join([f"'{p}/**/*.parquet'" for p in paths])
    query = f"""
        SELECT *
        FROM read_parquet([{globs}], hive_partitioning=1)
    """
    df = con.execute(query).df()
    if df.empty:
        return df

    # Keep observations from the requested local service date plus the next-day
    # after-midnight extension. Candidate service-date filtering happens below.
    return df


def _prediction_rows(raw_df: pd.DataFrame) -> list[dict]:
    rows: list[dict] = []
    for _, raw_row in raw_df.iterrows():
        tu = _safe_mapping(raw_row.get("trip_update"))
        if not tu:
            continue
        trip = tu.get("trip") or {}
        trip_id = trip.get("trip_id")
        route_id = trip.get("route_id")
        start_date = trip.get("start_date")
        schedule_relationship = trip.get("schedule_relationship")
        descriptor = trip.get("nyct_trip_descriptor") or {}
        direction = descriptor.get("direction") if isinstance(descriptor, dict) else None
        direction_id = trip.get("direction_id")
        observed_at = pd.to_numeric(raw_row.get("feed_timestamp"), errors="coerce")
        if pd.isna(observed_at):
            observed_at = pd.to_numeric(raw_row.get("fetched_at"), errors="coerce")

        for stu in tu.get("stop_time_update", []) or []:
            arrival = (stu.get("arrival") or {}).get("time")
            departure = (stu.get("departure") or {}).get("time")
            predicted = arrival if arrival is not None else departure
            if predicted is None or trip_id is None or stu.get("stop_id") is None:
                continue

            predicted_num = pd.to_numeric(predicted, errors="coerce")
            if pd.isna(predicted_num):
                continue

            rows.append(
                {
                    "trip_id": trip_id,
                    "route_id": route_id,
                    "direction": direction,
                    "direction_id": direction_id,
                    "stop_id": stu.get("stop_id"),
                    "stop_sequence": stu.get("stop_sequence"),
                    "schedule_relationship": schedule_relationship,
                    "trip_start_date": start_date,
                    "predicted_arrival": int(predicted_num),
                    "predicted_arrival_utc": datetime.fromtimestamp(
                        int(predicted_num), tz=timezone.utc
                    ).isoformat(),
                    "observed_at": int(observed_at) if pd.notna(observed_at) else None,
                    "observed_at_utc": (
                        datetime.fromtimestamp(int(observed_at), tz=timezone.utc).isoformat()
                        if pd.notna(observed_at)
                        else None
                    ),
                    "feed_name": raw_row.get("feed_name") or raw_row.get("line"),
                }
            )
    return rows


def extract_trip_updates(raw_df: pd.DataFrame) -> pd.DataFrame:
    """Return every prediction observation plus derived service-day context."""
    rows = _prediction_rows(raw_df)
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    for col in ("predicted_arrival", "observed_at", "stop_sequence", "direction_id"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["local_date"] = df["predicted_arrival"].map(local_date_from_unix)
    candidates = df["predicted_arrival"].map(service_date_candidates)
    df["service_date_candidates"] = candidates
    df["prediction_history_key"] = (
        df["trip_id"].astype(str) + "|" + df["stop_id"].astype(str)
    )

    # Keep rows belonging to the requested service date in main() rather than
    # collapsing to a single UTC date here.
    return df.reset_index(drop=True)


def latest_trip_updates(observations: pd.DataFrame, service_date: str) -> pd.DataFrame:
    """Select the terminal observed prediction per trip/stop for daily metrics."""
    if observations.empty:
        return observations.copy()
    mask = observations["service_date_candidates"].map(
        lambda pairs: service_date in {d for d, _ in pairs}
    )
    df = observations.loc[mask].copy()
    if df.empty:
        return df
    # Use feed observation time, not predicted time, as the history ordering key.
    df = df.sort_values(["prediction_history_key", "observed_at", "predicted_arrival"])
    return df.drop_duplicates("prediction_history_key", keep="last").reset_index(drop=True)


def extract_vehicle_positions(raw_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    for _, raw_row in raw_df.iterrows():
        veh = _safe_mapping(raw_row.get("vehicle"))
        if not veh:
            continue
        trip = veh.get("trip") or {}
        trip_id = trip.get("trip_id")
        if trip_id is None:
            continue
        timestamp = pd.to_numeric(veh.get("timestamp"), errors="coerce")
        rows.append(
            {
                "trip_id": trip_id,
                "route_id": trip.get("route_id"),
                "current_stop_id": veh.get("stop_id"),
                "current_status": veh.get("current_status"),
                "timestamp": int(timestamp) if pd.notna(timestamp) else None,
                "timestamp_utc": (
                    datetime.fromtimestamp(int(timestamp), tz=timezone.utc).isoformat()
                    if pd.notna(timestamp)
                    else None
                ),
                "feed_name": raw_row.get("feed_name") or raw_row.get("line"),
            }
        )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).dropna(subset=["trip_id"])
    df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce")
    return (
        df.sort_values("timestamp")
        .drop_duplicates(subset=["trip_id"], keep="last")
        .reset_index(drop=True)
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, default=(datetime.now(NY_TZ).date() - timedelta(days=1)).isoformat())
    args = parser.parse_args()

    raw_df = load_raw_snapshots(args.date)
    if raw_df.empty:
        log.warning("Nothing to process for %s", args.date)
        return

    observations = extract_trip_updates(raw_df)
    service_mask = observations["service_date_candidates"].map(
        lambda pairs: args.date in {d for d, _ in pairs}
    ) if not observations.empty else pd.Series(dtype=bool)
    observations_for_date = observations.loc[service_mask].copy() if not observations.empty else observations
    vehicle_positions = extract_vehicle_positions(raw_df)

    out_dir = PROCESSED_DATA_DIR / f"date={args.date}"
    out_dir.mkdir(parents=True, exist_ok=True)

    if not observations_for_date.empty:
        persisted_observations = observations_for_date.drop(columns=["service_date_candidates"])
        persisted_observations.to_parquet(out_dir / "trip_update_observations.parquet", index=False)
        latest = latest_trip_updates(observations_for_date, args.date)
        latest.drop(columns=["service_date_candidates"]).to_parquet(
            out_dir / "trip_updates.parquet", index=False
        )
        log.info(
            "Wrote %s prediction observations and %s terminal predictions for service date %s",
            len(observations_for_date), len(latest), args.date,
        )
    if not vehicle_positions.empty:
        vehicle_positions.to_parquet(out_dir / "vehicle_positions.parquet", index=False)
        log.info("Wrote %s latest vehicle positions", len(vehicle_positions))


if __name__ == "__main__":
    main()
