"""
Sanity checks that on-time percentage and delay aggregation math is
correct against a small known fixture.
"""
import pandas as pd
import pytest

from processing import metrics


@pytest.fixture
def synthetic_reconciled(tmp_path, monkeypatch):
    processed_dir = tmp_path / "date=2026-08-25"
    processed_dir.mkdir(parents=True)

    # 4 matched trips on line A: 3 on-time (<=5min), 1 late (10min)
    # 1 matched trip on line B: on-time
    # 1 ghost on line A
    df = pd.DataFrame(
        [
            {"trip_id": "1", "route_id": "A", "stop_id": "101", "line": "A",
             "static_trip_id": "S1", "scheduled_arrival_seconds": 28800,
             "pred_seconds_since_midnight": 28830, "delay_seconds": 30,
             "match_status": "matched"},
            {"trip_id": "2", "route_id": "A", "stop_id": "101", "line": "A",
             "static_trip_id": "S2", "scheduled_arrival_seconds": 29400,
             "pred_seconds_since_midnight": 29460, "delay_seconds": 60,
             "match_status": "matched"},
            {"trip_id": "3", "route_id": "A", "stop_id": "101", "line": "A",
             "static_trip_id": "S3", "scheduled_arrival_seconds": 30000,
             "pred_seconds_since_midnight": 30120, "delay_seconds": 120,
             "match_status": "matched"},
            {"trip_id": "4", "route_id": "A", "stop_id": "101", "line": "A",
             "static_trip_id": "S4", "scheduled_arrival_seconds": 30600,
             "pred_seconds_since_midnight": 31200, "delay_seconds": 600,
             "match_status": "matched"},
            {"trip_id": "5", "route_id": "B", "stop_id": "201", "line": "B",
             "static_trip_id": "S5", "scheduled_arrival_seconds": 28800,
             "pred_seconds_since_midnight": 28810, "delay_seconds": 10,
             "match_status": "matched"},
            {"trip_id": "6", "route_id": "A", "stop_id": "101", "line": "A",
             "static_trip_id": None, "scheduled_arrival_seconds": None,
             "pred_seconds_since_midnight": 40000, "delay_seconds": None,
             "match_status": "unmatched_ghost_candidate"},
        ]
    )

    out_dir = tmp_path
    df.to_parquet(processed_dir / "reconciled_trips.parquet", index=False)

    monkeypatch.setattr(metrics, "PROCESSED_DATA_DIR", out_dir)
    return out_dir


def test_on_time_pct_by_line(synthetic_reconciled):
    metrics.compute_metrics("2026-08-25")

    result = pd.read_parquet(
        synthetic_reconciled / "date=2026-08-25" / "on_time_by_line.parquet"
    )

    line_a = result[result["line"] == "A"].iloc[0]
    # 4 matched on line A, 3 within 5 min (30s, 60s, 120s), 1 not (600s)
    assert line_a["matched_count"] == 4
    assert line_a["on_time_count"] == 3
    assert line_a["on_time_pct"] == 75.0

    line_b = result[result["line"] == "B"].iloc[0]
    assert line_b["matched_count"] == 1
    assert line_b["on_time_pct"] == 100.0


def test_ghost_rate_by_line(synthetic_reconciled):
    metrics.compute_metrics("2026-08-25")

    result = pd.read_parquet(
        synthetic_reconciled / "date=2026-08-25" / "ghost_rate_by_line.parquet"
    )

    line_a = result[result["line"] == "A"].iloc[0]
    # 5 total predictions on line A (4 matched + 1 ghost), 1 ghost = 20%
    assert line_a["total_predictions"] == 5
    assert line_a["ghost_count"] == 1
    assert line_a["ghost_pct"] == 20.0
