"""Sanity checks for prediction-based daily metric math."""
import pandas as pd
import pytest

from processing import metrics


@pytest.fixture
def synthetic_reconciled(tmp_path, monkeypatch):
    processed_dir = tmp_path / "date=2026-08-25"
    processed_dir.mkdir(parents=True)

    base = pd.Timestamp("2026-08-25 08:00:00", tz="America/New_York")
    rows = []
    delays = [30, 60, 120, 600]
    for i, delay in enumerate(delays, 1):
        scheduled = 8 * 3600 + i * 600
        observed = int((base + pd.Timedelta(minutes=i)).timestamp())
        rows.append({
            "trip_id": str(i), "route_id": "A", "stop_id": "101", "feed_name": "ACE",
            "static_trip_id": f"S{i}", "scheduled_arrival_seconds": scheduled,
            "prediction_service_seconds": scheduled + delay,
            "prediction_delay_seconds": delay, "match_status": "matched", "observed_at": observed,
        })
    rows.append({
        "trip_id": "5", "route_id": "B", "stop_id": "201", "feed_name": "BDFM",
        "static_trip_id": "S5", "scheduled_arrival_seconds": 28800,
        "prediction_service_seconds": 28810, "prediction_delay_seconds": 10,
        "match_status": "matched", "observed_at": int((base + pd.Timedelta(minutes=5)).timestamp()),
    })
    rows.append({
        "trip_id": "6", "route_id": "A", "stop_id": "101", "feed_name": "ACE",
        "static_trip_id": None, "scheduled_arrival_seconds": None,
        "prediction_service_seconds": 40000, "prediction_delay_seconds": None,
        "match_status": "unmatched_prediction", "observed_at": int((base + pd.Timedelta(minutes=6)).timestamp()),
    })
    rows.append({
        "trip_id": "7", "route_id": "A", "stop_id": "101", "feed_name": "ACE",
        "static_trip_id": None, "scheduled_arrival_seconds": None,
        "prediction_service_seconds": 40010, "prediction_delay_seconds": None,
        "match_status": "ambiguous_prediction", "observed_at": int((base + pd.Timedelta(minutes=7)).timestamp()),
    })
    pd.DataFrame(rows).to_parquet(processed_dir / "reconciled_trips.parquet", index=False)
    monkeypatch.setattr(metrics, "PROCESSED_DATA_DIR", tmp_path)
    return tmp_path


def test_on_time_pct_by_line(synthetic_reconciled):
    metrics.compute_metrics("2026-08-25")
    result = pd.read_parquet(synthetic_reconciled / "date=2026-08-25" / "on_time_by_line.parquet")
    line_a = result[result["line"] == "A"].iloc[0]
    assert line_a["matched_count"] == 4
    assert line_a["on_time_count"] == 3
    assert line_a["on_time_pct"] == 75.0
    line_b = result[result["line"] == "B"].iloc[0]
    assert line_b["matched_count"] == 1
    assert line_b["on_time_pct"] == 100.0


def test_prediction_quality_groups_by_route_not_feed(synthetic_reconciled):
    metrics.compute_metrics("2026-08-25")
    result = pd.read_parquet(synthetic_reconciled / "date=2026-08-25" / "prediction_quality_by_line.parquet")
    line_a = result[result["route_id"] == "A"].iloc[0]
    assert line_a["total_predictions"] == 6
    assert line_a["unmatched_count"] == 1
    assert line_a["ambiguous_count"] == 1
    assert line_a["data_quality_issue_pct"] == pytest.approx(33.3, abs=0.1)
