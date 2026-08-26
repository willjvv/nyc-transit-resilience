"""
Computes summary metrics from reconciled_trips.parquet:

  - on_time_by_line: % of arrivals within threshold, per line, per day
  - delay_by_hour: mean/median delay by hour of day, per line
  - ghost_train_rate: % of realtime predictions with no schedule match

These summary tables are what dashboard/app.py reads - the dashboard
never touches raw or reconciled data directly, which keeps it fast and
keeps the "what counts as on-time" business logic in one place.

Usage:
    python -m processing.metrics --date 2026-08-25
"""
import argparse
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("metrics")

PROCESSED_DATA_DIR = Path(os.getenv("PROCESSED_DATA_DIR", "data/processed"))

# A train is "on time" if it's within this many seconds of its
# scheduled arrival. NYC Transit's own definition is roughly 5 minutes
# for numbered/lettered lines - adjust here if you want to match their
# official methodology exactly.
ON_TIME_THRESHOLD_SECONDS = 5 * 60


def compute_metrics(date: str) -> None:
    reconciled_path = PROCESSED_DATA_DIR / f"date={date}" / "reconciled_trips.parquet"
    if not reconciled_path.exists():
        log.warning("No reconciled_trips found for %s - run reconcile.py first", date)
        return

    con = duckdb.connect()
    out_dir = PROCESSED_DATA_DIR / f"date={date}"

    # On-time percentage by line
    on_time_by_line = con.execute(f"""
        SELECT
            line,
            COUNT(*) FILTER (WHERE match_status = 'matched') AS matched_count,
            COUNT(*) FILTER (
                WHERE match_status = 'matched'
                AND ABS(delay_seconds) <= {ON_TIME_THRESHOLD_SECONDS}
            ) AS on_time_count,
            ROUND(
                100.0 * COUNT(*) FILTER (
                    WHERE match_status = 'matched'
                    AND ABS(delay_seconds) <= {ON_TIME_THRESHOLD_SECONDS}
                ) / NULLIF(COUNT(*) FILTER (WHERE match_status = 'matched'), 0),
                1
            ) AS on_time_pct,
            ROUND(AVG(delay_seconds) FILTER (WHERE match_status = 'matched') / 60.0, 2)
                AS avg_delay_minutes
        FROM read_parquet('{reconciled_path}')
        GROUP BY line
        ORDER BY on_time_pct DESC
    """).df()
    on_time_by_line.to_parquet(out_dir / "on_time_by_line.parquet", index=False)

    # Delay by hour of day, per line - scheduled_arrival_seconds encodes
    # hour of day directly (seconds since service-day midnight)
    delay_by_hour = con.execute(f"""
        SELECT
            line,
            CAST(scheduled_arrival_seconds / 3600 AS INTEGER) % 24 AS hour_of_day,
            COUNT(*) AS n_trips,
            ROUND(AVG(delay_seconds) / 60.0, 2) AS avg_delay_minutes,
            ROUND(MEDIAN(delay_seconds) / 60.0, 2) AS median_delay_minutes
        FROM read_parquet('{reconciled_path}')
        WHERE match_status = 'matched'
        GROUP BY line, hour_of_day
        ORDER BY line, hour_of_day
    """).df()
    delay_by_hour.to_parquet(out_dir / "delay_by_hour.parquet", index=False)

    # Ghost train rate by line
    ghost_rate = con.execute(f"""
        SELECT
            line,
            COUNT(*) AS total_predictions,
            COUNT(*) FILTER (WHERE match_status = 'unmatched_ghost_candidate') AS ghost_count,
            ROUND(
                100.0 * COUNT(*) FILTER (WHERE match_status = 'unmatched_ghost_candidate')
                / NULLIF(COUNT(*), 0),
                1
            ) AS ghost_pct
        FROM read_parquet('{reconciled_path}')
        GROUP BY line
        ORDER BY ghost_pct DESC
    """).df()
    ghost_rate.to_parquet(out_dir / "ghost_rate_by_line.parquet", index=False)

    log.info(
        "Wrote metrics for %s: on_time_by_line (%s rows), delay_by_hour (%s rows), "
        "ghost_rate_by_line (%s rows)",
        date,
        len(on_time_by_line),
        len(delay_by_hour),
        len(ghost_rate),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--date",
        type=str,
        default=(datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d"),
    )
    args = parser.parse_args()
    compute_metrics(args.date)


if __name__ == "__main__":
    main()
