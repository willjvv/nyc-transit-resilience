"""Daily metrics over reconciled realtime *predictions*.

Important semantic boundary: GTFS-realtime TripUpdates provide predicted arrival
times, not authoritative observed arrival timestamps. The metrics below therefore
measure the final observed prediction for each trip/stop, not actual arrival time.
"""
from __future__ import annotations

import argparse
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("metrics")

PROCESSED_DATA_DIR = Path(os.getenv("PROCESSED_DATA_DIR", "data/processed"))
ON_TIME_THRESHOLD_SECONDS = 5 * 60


def compute_metrics(date: str) -> None:
    reconciled_path = PROCESSED_DATA_DIR / f"date={date}" / "reconciled_trips.parquet"
    if not reconciled_path.exists():
        log.warning("No reconciled_trips found for %s - run reconcile.py first", date)
        return

    out_dir = PROCESSED_DATA_DIR / f"date={date}"
    con = duckdb.connect()
    # The reconciliation table can contain the full prediction history. Daily
    # reliability uses the terminal prediction per realtime trip/stop so a train
    # observed in 10 polls is not counted 10 times.
    terminal = con.execute(f"""
        SELECT * EXCLUDE (rn)
        FROM (
            SELECT *,
                   ROW_NUMBER() OVER (
                       PARTITION BY trip_id, stop_id
                       ORDER BY observed_at DESC NULLS LAST, predicted_arrival DESC
                   ) AS rn
            FROM read_parquet('{reconciled_path}')
        )
        WHERE rn = 1
    """).df()
    terminal.to_parquet(out_dir / "terminal_predictions.parquet", index=False)

    # Route_id is the actual subway line identifier. feed_name is retained as a
    # separate source-feed dimension and never used as the line identity.
    on_time = con.execute(f"""
        SELECT
            route_id AS line,
            route_id,
            COUNT(*) FILTER (WHERE match_status = 'matched') AS matched_count,
            COUNT(*) FILTER (
                WHERE match_status = 'matched'
                  AND ABS(prediction_delay_seconds) <= {ON_TIME_THRESHOLD_SECONDS}
            ) AS on_time_count,
            ROUND(
                100.0 * COUNT(*) FILTER (
                    WHERE match_status = 'matched'
                      AND ABS(prediction_delay_seconds) <= {ON_TIME_THRESHOLD_SECONDS}
                ) / NULLIF(COUNT(*) FILTER (WHERE match_status = 'matched'), 0),
                1
            ) AS on_time_pct,
            ROUND(AVG(prediction_delay_seconds) FILTER (WHERE match_status = 'matched') / 60.0, 2)
                AS avg_prediction_delay_minutes
        FROM read_parquet('{out_dir / "terminal_predictions.parquet"}')
        WHERE route_id IS NOT NULL
        GROUP BY route_id
        ORDER BY on_time_pct DESC
    """).df()
    # Preserve the dashboard's historical column while adding a semantically precise name.
    on_time["avg_delay_minutes"] = on_time["avg_prediction_delay_minutes"]
    on_time.to_parquet(out_dir / "on_time_by_line.parquet", index=False)

    delay_by_hour = con.execute(f"""
        SELECT
            route_id AS line,
            route_id,
            CAST(prediction_service_seconds / 3600 AS INTEGER) % 24 AS hour_of_day,
            COUNT(*) AS n_trips,
            ROUND(AVG(prediction_delay_seconds) / 60.0, 2) AS avg_prediction_delay_minutes,
            ROUND(MEDIAN(prediction_delay_seconds) / 60.0, 2) AS median_prediction_delay_minutes
        FROM read_parquet('{out_dir / "terminal_predictions.parquet"}')
        WHERE match_status = 'matched'
          AND prediction_service_seconds IS NOT NULL
        GROUP BY route_id, hour_of_day
        ORDER BY route_id, hour_of_day
    """).df()
    delay_by_hour["avg_delay_minutes"] = delay_by_hour["avg_prediction_delay_minutes"]
    delay_by_hour.to_parquet(out_dir / "delay_by_hour.parquet", index=False)

    data_quality = con.execute(f"""
        SELECT
            route_id AS line,
            route_id,
            COUNT(*) AS total_predictions,
            COUNT(*) FILTER (WHERE match_status = 'unmatched_prediction') AS unmatched_count,
            COUNT(*) FILTER (WHERE match_status = 'ambiguous_prediction') AS ambiguous_count,
            COUNT(*) FILTER (WHERE match_status = 'added_service') AS added_service_count,
            ROUND(
                100.0 * COUNT(*) FILTER (WHERE match_status IN ('unmatched_prediction', 'ambiguous_prediction'))
                / NULLIF(COUNT(*), 0),
                1
            ) AS data_quality_issue_pct
        FROM read_parquet('{out_dir / "terminal_predictions.parquet"}')
        WHERE route_id IS NOT NULL
        GROUP BY route_id
        ORDER BY data_quality_issue_pct DESC
    """).df()
    data_quality.to_parquet(out_dir / "prediction_quality_by_line.parquet", index=False)
    # Backward-compatible legacy artifact for existing dashboard consumers.
    legacy_quality = data_quality.copy()
    legacy_quality["ghost_count"] = legacy_quality["unmatched_count"]
    legacy_quality["ghost_pct"] = legacy_quality["data_quality_issue_pct"]
    legacy_quality.to_parquet(out_dir / "ghost_rate_by_line.parquet", index=False)

    log.info("Wrote prediction-based metrics for %s", date)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, default=(datetime.now(ZoneInfo("America/New_York")).date() - timedelta(days=1)).isoformat())
    args = parser.parse_args()
    compute_metrics(args.date)


if __name__ == "__main__":
    main()
