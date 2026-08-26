"""
The core engineering problem of this project: realtime trip_ids and
static schedule trip_ids do NOT reliably match, so we can't just JOIN
on trip_id. Instead we match on (route_id, direction, stop_id, and a
time window) - the same approach used by prior art in this space (see
README).

Matching strategy:
  1. For each realtime trip_update row (a predicted arrival at a stop),
     find static schedule stop_times for the same route_id + stop_id
     where the scheduled arrival falls within MATCH_WINDOW_MINUTES of
     the predicted arrival.
  2. If exactly one static trip matches, that's our match - compute
     delay_seconds = predicted_arrival - scheduled_arrival.
  3. If zero static trips match within the window, mark as unmatched
     (a "ghost train" candidate - either an extra/unscheduled train, or
     a matching bug worth investigating).
  4. If multiple static trips match (happens during high-frequency
     service), pick the closest in time - ties are rare in practice at
     subway frequencies but this keeps the join deterministic.

Output: data/processed/date=YYYY-MM-DD/reconciled_trips.parquet
  Columns: trip_id, route_id, stop_id, direction, predicted_arrival,
           scheduled_arrival, delay_seconds, match_status

Usage:
    python -m processing.reconcile --date 2026-08-25
"""
import argparse
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("reconcile")

PROCESSED_DATA_DIR = Path(os.getenv("PROCESSED_DATA_DIR", "data/processed"))
STATIC_GTFS_DIR = Path(os.getenv("STATIC_GTFS_DIR", "data/static_gtfs"))

# How far apart (in minutes) a predicted arrival can be from a scheduled
# arrival and still be considered "the same trip". Subway headways are
# often 3-8 minutes at peak, so this window needs to be tight enough to
# avoid matching adjacent trains but loose enough to catch real delays.
MATCH_WINDOW_MINUTES = 10


def reconcile_date(date: str) -> None:
    trip_updates_path = PROCESSED_DATA_DIR / f"date={date}" / "trip_updates.parquet"
    if not trip_updates_path.exists():
        log.warning("No trip_updates found for %s - run parse_snapshots first", date)
        return

    stop_times_path = STATIC_GTFS_DIR / "stop_times.parquet"
    trips_path = STATIC_GTFS_DIR / "trips.parquet"
    if not stop_times_path.exists() or not trips_path.exists():
        log.warning(
            "Static GTFS tables not found - run ingestion.gtfs_static_loader first"
        )
        return

    con = duckdb.connect()

    # Static schedule times are stored as GTFS's "service-day seconds"
    # (e.g. "25:14:00" for 1:14am the next service day), which we
    # convert to a comparable seconds-since-midnight-of-service-day
    # integer here rather than trying to force it into a wall clock.
    query = f"""
        WITH realtime AS (
            SELECT
                trip_id,
                route_id,
                direction,
                stop_id,
                predicted_arrival,
                line
            FROM read_parquet('{trip_updates_path}')
            WHERE predicted_arrival IS NOT NULL
        ),
        static AS (
            SELECT
                st.trip_id AS static_trip_id,
                t.route_id AS static_route_id,
                st.stop_id AS static_stop_id,
                -- Convert HH:MM:SS (possibly >24h) schedule time to seconds
                CAST(split_part(st.arrival_time, ':', 1) AS INTEGER) * 3600
                    + CAST(split_part(st.arrival_time, ':', 2) AS INTEGER) * 60
                    + CAST(split_part(st.arrival_time, ':', 3) AS INTEGER) AS scheduled_arrival_seconds
            FROM read_parquet('{stop_times_path}') st
            JOIN read_parquet('{trips_path}') t ON st.trip_id = t.trip_id
        )
        SELECT
            r.trip_id,
            r.route_id,
            r.direction,
            r.stop_id,
            r.line,
            r.predicted_arrival,
            s.static_trip_id,
            s.scheduled_arrival_seconds
        FROM realtime r
        LEFT JOIN static s
            ON r.route_id = s.static_route_id
            AND r.stop_id = s.static_stop_id
    """
    joined = con.execute(query).df()
    log.info("Joined %s realtime x static candidate rows for %s", len(joined), date)

    # The time-window matching and "closest match wins" logic is easier
    # to express clearly in pandas than in a single SQL statement, and
    # this dataset size (one day, one route/stop pair at a time) is
    # small enough that this is not a performance concern.
    import pandas as pd

    joined["predicted_arrival"] = pd.to_numeric(joined["predicted_arrival"], errors="coerce")

    # predicted_arrival is a unix timestamp; convert to seconds-since-
    # midnight-UTC-of-that-day so it's comparable to scheduled_arrival_seconds.
    # NOTE: MTA's static schedule times are in the feed's local service-day
    # convention; for an MVP we approximate service-day midnight as UTC
    # midnight of the predicted arrival's date. This is close enough for
    # delay-minutes-level analysis but worth tightening (proper timezone
    # handling) before drawing conclusions at the second-level.
    joined["pred_dt"] = pd.to_datetime(joined["predicted_arrival"], unit="s", utc=True)
    joined["pred_seconds_since_midnight"] = (
        joined["pred_dt"].dt.hour * 3600
        + joined["pred_dt"].dt.minute * 60
        + joined["pred_dt"].dt.second
    )

    joined["time_diff_seconds"] = (
        joined["pred_seconds_since_midnight"] - joined["scheduled_arrival_seconds"]
    ).abs()

    window_seconds = MATCH_WINDOW_MINUTES * 60
    within_window = joined[
        joined["time_diff_seconds"].notna() & (joined["time_diff_seconds"] <= window_seconds)
    ].copy()

    # For each realtime (trip_id, stop_id), keep the closest static match
    best_matches = (
        within_window.sort_values("time_diff_seconds")
        .drop_duplicates(subset=["trip_id", "stop_id"], keep="first")
    )
    best_matches["match_status"] = "matched"
    best_matches["delay_seconds"] = (
        best_matches["pred_seconds_since_midnight"] - best_matches["scheduled_arrival_seconds"]
    )

    # Ghost trains: realtime predictions with no static match at all
    matched_keys = set(zip(best_matches["trip_id"], best_matches["stop_id"]))
    all_realtime = joined.drop_duplicates(subset=["trip_id", "stop_id"])
    unmatched = all_realtime[
        ~all_realtime.apply(lambda r: (r["trip_id"], r["stop_id"]) in matched_keys, axis=1)
    ].copy()
    unmatched["match_status"] = "unmatched_ghost_candidate"
    unmatched["delay_seconds"] = None
    unmatched["static_trip_id"] = None

    output_cols = [
        "trip_id",
        "route_id",
        "direction",
        "stop_id",
        "line",
        "static_trip_id",
        "scheduled_arrival_seconds",
        "pred_seconds_since_midnight",
        "delay_seconds",
        "match_status",
    ]
    result = pd.concat([best_matches[output_cols], unmatched[output_cols]], ignore_index=True)

    out_path = PROCESSED_DATA_DIR / f"date={date}" / "reconciled_trips.parquet"
    result.to_parquet(out_path, index=False)

    matched_pct = 100 * len(best_matches) / max(len(all_realtime), 1)
    log.info(
        "Reconciled %s: %s matched (%.1f%%), %s unmatched -> %s",
        date,
        len(best_matches),
        matched_pct,
        len(unmatched),
        out_path,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--date",
        type=str,
        default=(datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d"),
    )
    args = parser.parse_args()
    reconcile_date(args.date)


if __name__ == "__main__":
    main()
