"""
Unit tests for the reconciliation matching logic. Uses small synthetic
Parquet fixtures written to a temp directory rather than real MTA data,
so tests run fast and deterministically.
"""
import os
from pathlib import Path

import pandas as pd
import pytest

from processing import reconcile


@pytest.fixture
def synthetic_gtfs(tmp_path, monkeypatch):
    """Build a minimal static schedule + realtime trip_updates fixture
    covering: an exact match, a delayed-but-matchable train, and an
    unmatched ghost train."""
    static_dir = tmp_path / "static_gtfs"
    processed_dir = tmp_path / "processed" / "date=2026-08-25"
    static_dir.mkdir(parents=True)
    processed_dir.mkdir(parents=True)

    trips = pd.DataFrame(
        [
            {"trip_id": "SCHED_1", "route_id": "A"},
            {"trip_id": "SCHED_2", "route_id": "A"},
        ]
    )
    trips.to_parquet(static_dir / "trips.parquet", index=False)

    stop_times = pd.DataFrame(
        [
            # Scheduled for 08:00:00 at stop 101
            {"trip_id": "SCHED_1", "stop_id": "101", "arrival_time": "08:00:00"},
            # Scheduled for 08:10:00 at stop 101
            {"trip_id": "SCHED_2", "stop_id": "101", "arrival_time": "08:10:00"},
        ]
    )
    stop_times.to_parquet(static_dir / "stop_times.parquet", index=False)

    # Realtime predictions:
    #   - RT_1 at stop 101, predicted 08:00:30 -> should match SCHED_1 (30s delay)
    #   - RT_2 at stop 101, predicted 08:14:00 -> should match SCHED_2 (4 min delay)
    #   - RT_3 at stop 101, predicted 09:30:00 -> no schedule within window -> ghost
    base = pd.Timestamp("2026-08-25", tz="UTC")
    trip_updates = pd.DataFrame(
        [
            {
                "trip_id": "RT_1",
                "route_id": "A",
                "direction": "N",
                "stop_id": "101",
                "line": "A",
                "predicted_arrival": int((base + pd.Timedelta(hours=8, seconds=30)).timestamp()),
            },
            {
                "trip_id": "RT_2",
                "route_id": "A",
                "direction": "N",
                "stop_id": "101",
                "line": "A",
                "predicted_arrival": int((base + pd.Timedelta(hours=8, minutes=14)).timestamp()),
            },
            {
                "trip_id": "RT_3",
                "route_id": "A",
                "direction": "N",
                "stop_id": "101",
                "line": "A",
                "predicted_arrival": int((base + pd.Timedelta(hours=9, minutes=30)).timestamp()),
            },
        ]
    )
    trip_updates.to_parquet(processed_dir / "trip_updates.parquet", index=False)

    monkeypatch.setattr(reconcile, "STATIC_GTFS_DIR", static_dir)
    monkeypatch.setattr(reconcile, "PROCESSED_DATA_DIR", tmp_path / "processed")

    return tmp_path / "processed"


def test_reconcile_matches_within_window(synthetic_gtfs):
    reconcile.reconcile_date("2026-08-25")

    out_path = synthetic_gtfs / "date=2026-08-25" / "reconciled_trips.parquet"
    assert out_path.exists()

    result = pd.read_parquet(out_path)

    rt1 = result[result["trip_id"] == "RT_1"].iloc[0]
    assert rt1["match_status"] == "matched"
    assert rt1["static_trip_id"] == "SCHED_1"
    assert abs(rt1["delay_seconds"] - 30) < 1

    rt2 = result[result["trip_id"] == "RT_2"].iloc[0]
    assert rt2["match_status"] == "matched"
    assert rt2["static_trip_id"] == "SCHED_2"
    assert abs(rt2["delay_seconds"] - 240) < 1


def test_reconcile_flags_ghost_trains(synthetic_gtfs):
    reconcile.reconcile_date("2026-08-25")

    out_path = synthetic_gtfs / "date=2026-08-25" / "reconciled_trips.parquet"
    result = pd.read_parquet(out_path)

    rt3 = result[result["trip_id"] == "RT_3"].iloc[0]
    assert rt3["match_status"] == "unmatched_ghost_candidate"
    assert pd.isna(rt3["delay_seconds"])


def test_reconcile_missing_inputs_does_not_raise(tmp_path, monkeypatch):
    monkeypatch.setattr(reconcile, "STATIC_GTFS_DIR", tmp_path / "nonexistent")
    monkeypatch.setattr(reconcile, "PROCESSED_DATA_DIR", tmp_path / "also_nonexistent")
    # Should log a warning and return cleanly, not raise
    reconcile.reconcile_date("2026-01-01")
