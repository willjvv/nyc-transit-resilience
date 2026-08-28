"""Reconcile realtime predictions with the active static GTFS schedule.

This module treats a realtime trip update as a *prediction*, not an observed
arrival. Each prediction gets matched to an active scheduled stop-time using:

  1. service date / calendar validity
  2. route_id
  3. stop_id
  4. stop_sequence when supplied by GTFS-RT
  5. direction when available
  6. nearest service-day arrival time within a bounded window

Ambiguous candidates are retained as ambiguous instead of silently assigning
the prediction to the wrong train.
"""
from __future__ import annotations

import argparse
import logging
import os
from bisect import bisect_left
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from processing.time_utils import NY_TZ, parse_gtfs_time, service_date_candidates, service_date_from_gtfs_date

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("reconcile")

PROCESSED_DATA_DIR = Path(os.getenv("PROCESSED_DATA_DIR", "data/processed"))
STATIC_GTFS_DIR = Path(os.getenv("STATIC_GTFS_DIR", "data/static_gtfs"))
MATCH_WINDOW_MINUTES = 10
AMBIGUITY_MARGIN_SECONDS = 60
HIGH_CONFIDENCE_SECONDS = 60
LOW_CONFIDENCE_SECONDS = 8 * 60


def _load_active_service_ids(service_date: str) -> set[str]:
    calendar_path = STATIC_GTFS_DIR / "calendar.parquet"
    if not calendar_path.exists():
        raise FileNotFoundError(f"Missing {calendar_path}")

    # Service dates are New York local dates, parse with NY timezone context
    target = datetime.strptime(service_date, "%Y-%m-%d").replace(tzinfo=NY_TZ).date()
    weekday_column = target.strftime("%A").lower()
    calendar = pd.read_parquet(calendar_path)
    active: set[str] = set()

    for _, row in calendar.iterrows():
        start = str(row.get("start_date", ""))
        end = str(row.get("end_date", ""))
        if len(start) != 8 or len(end) != 8:
            continue
        try:
            start_d = datetime.strptime(start, "%Y%m%d").date()
            end_d = datetime.strptime(end, "%Y%m%d").date()
        except ValueError:
            continue
        if not (start_d <= target <= end_d):
            continue
        if str(row.get(weekday_column, "0")) != "1":
            continue
        active.add(str(row["service_id"]))

    # calendar_dates is an optional GTFS exception table; support additions/removals
    # when the static loader has captured it.
    exceptions_path = STATIC_GTFS_DIR / "calendar_dates.parquet"
    if exceptions_path.exists():
        exceptions = pd.read_parquet(exceptions_path)
        day = target.strftime("%Y%m%d")
        day_rows = exceptions[exceptions["date"].astype(str) == day]
        for _, row in day_rows.iterrows():
            sid = str(row["service_id"])
            if int(row["exception_type"]) == 1:
                active.add(sid)
            elif int(row["exception_type"]) == 2:
                active.discard(sid)
    return active


def _static_schedule(service_date: str) -> pd.DataFrame:
    stops_path = STATIC_GTFS_DIR / "stop_times.parquet"
    trips_path = STATIC_GTFS_DIR / "trips.parquet"
    if not stops_path.exists() or not trips_path.exists():
        raise FileNotFoundError("Static GTFS trips.parquet and stop_times.parquet are required")

    active_services = _load_active_service_ids(service_date)
    trips = pd.read_parquet(trips_path)
    stop_times = pd.read_parquet(stops_path)

    if "service_id" in trips.columns and active_services:
        trips = trips[trips["service_id"].astype(str).isin(active_services)].copy()
    elif "service_id" in trips.columns and not active_services:
        trips = trips.iloc[0:0].copy()

    keep_trip_cols = [c for c in ["trip_id", "route_id", "direction_id", "service_id"] if c in trips.columns]
    schedule = stop_times.merge(trips[keep_trip_cols], on="trip_id", how="inner")
    schedule["scheduled_arrival_seconds"] = schedule["arrival_time"].map(parse_gtfs_time)
    schedule = schedule.dropna(subset=["scheduled_arrival_seconds", "route_id", "stop_id"])
    schedule["scheduled_arrival_seconds"] = schedule["scheduled_arrival_seconds"].astype(int)
    schedule["service_date"] = service_date
    schedule["direction_id"] = pd.to_numeric(schedule.get("direction_id"), errors="coerce") if "direction_id" in schedule else pd.Series(index=schedule.index, dtype="float64")
    schedule["stop_sequence"] = pd.to_numeric(schedule.get("stop_sequence"), errors="coerce") if "stop_sequence" in schedule else pd.Series(index=schedule.index, dtype="float64")
    return schedule[
        [
            "trip_id", "route_id", "stop_id", "direction_id", "stop_sequence",
            "service_id", "service_date", "scheduled_arrival_seconds"
        ]
    ].rename(columns={"trip_id": "static_trip_id"})


def _prediction_service_seconds(row: pd.Series, service_date: str) -> int | None:
    predicted = pd.to_numeric(row.get("predicted_arrival"), errors="coerce")
    if pd.isna(predicted):
        return None
    start_date = service_date_from_gtfs_date(row.get("trip_start_date"))
    candidates = service_date_candidates(int(predicted))
    if start_date:
        for candidate_date, seconds in candidates:
            if candidate_date == start_date:
                return seconds
    for candidate_date, seconds in candidates:
        if candidate_date == service_date:
            return seconds
    return None


def _norm_direction(value) -> str | None:
    """Normalize GTFS direction_id values so 0, 0.0, and "0" compare equally."""
    if value is None or pd.isna(value):
        return None
    try:
        return str(int(float(value)))
    except (TypeError, ValueError):
        return str(value)


def _prediction_confidence(best_diff: float, second_diff: float | None, has_sequence: bool, direction_match: bool | None) -> float:
    # Time is the continuous evidence; structural fields add confidence.
    score = max(0.0, 1.0 - (best_diff / LOW_CONFIDENCE_SECONDS))
    if best_diff <= HIGH_CONFIDENCE_SECONDS:
        score = max(score, 0.95)
    if has_sequence:
        score = min(1.0, score + 0.20)
    if direction_match is True:
        score = min(1.0, score + 0.10)
    if second_diff is not None and second_diff - best_diff < AMBIGUITY_MARGIN_SECONDS:
        score *= 0.55
    return round(score, 4)


def _candidate_matches(predictions: pd.DataFrame, schedule: pd.DataFrame, service_date: str) -> pd.DataFrame:
    if predictions.empty:
        return pd.DataFrame()

    # Build small sorted indexes for each service/route/stop/direction/sequence bucket.
    indexes: dict[tuple, list[dict]] = {}
    for _, s in schedule.iterrows():
        base_key = (str(s.route_id), str(s.stop_id), _norm_direction(s.direction_id))
        for key in (base_key, (str(s.route_id), str(s.stop_id), None)):
            indexes.setdefault(key, []).append(s.to_dict())
    for key in indexes:
        indexes[key].sort(key=lambda x: x["scheduled_arrival_seconds"])

    rows = []
    window = MATCH_WINDOW_MINUTES * 60
    for _, r in predictions.iterrows():
        service_seconds = _prediction_service_seconds(r, service_date)
        base_output = {
            "trip_id": r.get("trip_id"),
            "route_id": r.get("route_id"),
            "direction": r.get("direction"),
            "direction_id": r.get("direction_id"),
            "stop_id": r.get("stop_id"),
            "stop_sequence": r.get("stop_sequence"),
            "feed_name": r.get("feed_name"),
            "predicted_arrival": r.get("predicted_arrival"),
            "predicted_arrival_utc": r.get("predicted_arrival_utc"),
            "observed_at": r.get("observed_at"),
            "observed_at_utc": r.get("observed_at_utc"),
            "schedule_relationship": r.get("schedule_relationship"),
            "trip_start_date": r.get("trip_start_date"),
            "service_date": service_date,
            "measurement_type": "realtime_prediction",
            "prediction_service_seconds": service_seconds,
        }
        if service_seconds is None or pd.isna(r.get("route_id")):
            base_output.update({"match_status": "unmatched_prediction", "static_trip_id": None, "scheduled_arrival_seconds": None})
            rows.append(base_output)
            continue

        # Added service is not a data-quality failure when GTFS-RT explicitly says so.
        # Check this before candidate matching to avoid false "unmatched" status.
        relationship = str(r.get("schedule_relationship") or "").upper()
        if relationship == "ADDED":
            base_output.update({"match_status": "added_service", "static_trip_id": None, "scheduled_arrival_seconds": None})
            rows.append(base_output)
            continue

        direction_id = _norm_direction(r.get("direction_id"))
        key = (str(r["route_id"]), str(r["stop_id"]), direction_id)
        candidates = indexes.get(key, [])
        if not candidates:
            candidates = indexes.get((str(r["route_id"]), str(r["stop_id"]), None), [])

        sequence = pd.to_numeric(r.get("stop_sequence"), errors="coerce")
        if pd.notna(sequence):
            seq_candidates = [c for c in candidates if pd.notna(c.get("stop_sequence")) and int(c["stop_sequence"]) == int(sequence)]
            if seq_candidates:
                candidates = seq_candidates

        if not candidates:
            base_output.update({"match_status": "unmatched_prediction", "static_trip_id": None, "scheduled_arrival_seconds": None})
            rows.append(base_output)
            continue

        times = [int(c["scheduled_arrival_seconds"]) for c in candidates]
        idx = bisect_left(times, service_seconds)
        nearby = []
        for i in range(max(0, idx - 2), min(len(candidates), idx + 3)):
            diff = abs(times[i] - service_seconds)
            if diff <= window:
                nearby.append((diff, candidates[i]))
        nearby.sort(key=lambda x: (x[0], str(x[1]["static_trip_id"])))

        if not nearby and relationship == "DUPLICATED":
            base_output.update({"match_status": "added_service", "static_trip_id": None, "scheduled_arrival_seconds": None})
            rows.append(base_output)
            continue

        if not nearby:
            base_output.update({"match_status": "unmatched_prediction", "static_trip_id": None, "scheduled_arrival_seconds": None})
            rows.append(base_output)
            continue

        best_diff, best = nearby[0]
        second_diff = nearby[1][0] if len(nearby) > 1 else None
        direction_match = None
        if pd.notna(r.get("direction_id")) and pd.notna(best.get("direction_id")):
            direction_match = int(r["direction_id"]) == int(best["direction_id"])
        ambiguous = second_diff is not None and (second_diff - best_diff) < AMBIGUITY_MARGIN_SECONDS and best_diff > HIGH_CONFIDENCE_SECONDS
        status = "ambiguous_prediction" if ambiguous else "matched"
        confidence = _prediction_confidence(best_diff, second_diff, pd.notna(r.get("stop_sequence")), direction_match)

        base_output.update(
            {
                "static_trip_id": best["static_trip_id"],
                "scheduled_arrival_seconds": int(best["scheduled_arrival_seconds"]),
                "match_status": status,
                "match_confidence": confidence,
                "candidate_count": len(nearby),
                "candidate_time_gap_seconds": (second_diff - best_diff) if second_diff is not None else None,
            }
        )
        base_output["prediction_delay_seconds"] = service_seconds - int(best["scheduled_arrival_seconds"])
        rows.append(base_output)

    result = pd.DataFrame(rows)
    if "prediction_delay_seconds" not in result:
        result["prediction_delay_seconds"] = pd.NA
    return result


def reconcile_date(service_date: str) -> None:
    date_dir = PROCESSED_DATA_DIR / f"date={service_date}"
    observations_path = date_dir / "trip_update_observations.parquet"
    legacy_path = date_dir / "trip_updates.parquet"
    input_path = observations_path if observations_path.exists() else legacy_path
    if not input_path.exists():
        log.warning("No realtime prediction data found for %s - run parse_snapshots first", service_date)
        return

    try:
        observations = pd.read_parquet(input_path)
        schedule = _static_schedule(service_date)
    except FileNotFoundError as exc:
        log.warning("%s", exc)
        return

    if observations.empty:
        log.warning("No predictions found for %s", service_date)
        return

    result = _candidate_matches(observations, schedule, service_date)
    output = date_dir / "reconciled_trips.parquet"
    result.to_parquet(output, index=False)

    counts = result["match_status"].value_counts().to_dict()
    log.info("Reconciled %s -> %s (%s)", service_date, output, counts)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, default=(datetime.now(NY_TZ).date() - timedelta(days=1)).isoformat())
    args = parser.parse_args()
    reconcile_date(args.date)


if __name__ == "__main__":
    main()
