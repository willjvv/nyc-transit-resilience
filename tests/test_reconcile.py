"""Reconciliation tests covering service dates, calendar rules, ambiguity and exceptions."""
import pandas as pd
import pytest

from processing import reconcile


@pytest.fixture
def synthetic_gtfs(tmp_path, monkeypatch):
    static_dir = tmp_path / "static_gtfs"
    date_dir = tmp_path / "processed" / "date=2026-08-25"
    static_dir.mkdir(parents=True)
    date_dir.mkdir(parents=True)

    trips = pd.DataFrame([
        {"trip_id": "SCHED_1", "route_id": "A", "direction_id": 0, "service_id": "WKD"},
        {"trip_id": "SCHED_2", "route_id": "A", "direction_id": 0, "service_id": "WKD"},
        {"trip_id": "SUNDAY", "route_id": "A", "direction_id": 0, "service_id": "SUN"},
    ])
    trips.to_parquet(static_dir / "trips.parquet", index=False)
    pd.DataFrame([
        {"trip_id": "SCHED_1", "stop_id": "101", "stop_sequence": 5, "arrival_time": "08:00:00"},
        {"trip_id": "SCHED_2", "stop_id": "101", "stop_sequence": 5, "arrival_time": "08:10:00"},
        {"trip_id": "SUNDAY", "stop_id": "101", "stop_sequence": 5, "arrival_time": "08:00:00"},
    ]).to_parquet(static_dir / "stop_times.parquet", index=False)
    pd.DataFrame([{
        "service_id": "WKD", "monday": 1, "tuesday": 1, "wednesday": 1, "thursday": 1,
        "friday": 1, "saturday": 0, "sunday": 0, "start_date": "20260101", "end_date": "20261231"
    }, {
        "service_id": "SUN", "monday": 0, "tuesday": 0, "wednesday": 0, "thursday": 0,
        "friday": 0, "saturday": 0, "sunday": 1, "start_date": "20260101", "end_date": "20261231"
    }]).to_parquet(static_dir / "calendar.parquet", index=False)

    base = pd.Timestamp("2026-08-25", tz="UTC")
    pd.DataFrame([
        {"trip_id": "RT_1", "route_id": "A", "direction": "N", "direction_id": 0, "stop_id": "101", "stop_sequence": 5,
         "feed_name": "ACE", "trip_start_date": "20260825", "schedule_relationship": None,
         "predicted_arrival": int((base + pd.Timedelta(hours=8, seconds=30)).timestamp()), "predicted_arrival_utc": (base + pd.Timedelta(hours=8, seconds=30)).isoformat(),
         "observed_at": int((base + pd.Timedelta(hours=7, minutes=55)).timestamp()), "observed_at_utc": (base + pd.Timedelta(hours=7, minutes=55)).isoformat()},
        {"trip_id": "RT_2", "route_id": "A", "direction": "N", "direction_id": 0, "stop_id": "101", "stop_sequence": 5,
         "feed_name": "ACE", "trip_start_date": "20260825", "schedule_relationship": None,
         "predicted_arrival": int((base + pd.Timedelta(hours=8, minutes=14)).timestamp()), "predicted_arrival_utc": (base + pd.Timedelta(hours=8, minutes=14)).isoformat(),
         "observed_at": int((base + pd.Timedelta(hours=8)).timestamp()), "observed_at_utc": (base + pd.Timedelta(hours=8)).isoformat()},
    ]).to_parquet(date_dir / "trip_update_observations.parquet", index=False)

    monkeypatch.setattr(reconcile, "STATIC_GTFS_DIR", static_dir)
    monkeypatch.setattr(reconcile, "PROCESSED_DATA_DIR", tmp_path / "processed")
    return tmp_path / "processed"


def test_reconcile_service_date_and_delay(synthetic_gtfs):
    reconcile.reconcile_date("2026-08-25")
    result = pd.read_parquet(synthetic_gtfs / "date=2026-08-25" / "reconciled_trips.parquet")
    rt1 = result[result.trip_id == "RT_1"].iloc[0]
    rt2 = result[result.trip_id == "RT_2"].iloc[0]
    assert rt1.static_trip_id == "SCHED_1"
    assert rt1.prediction_delay_seconds == 30
    assert rt2.static_trip_id == "SCHED_2"
    assert rt2.prediction_delay_seconds == 240
    assert rt1.measurement_type == "realtime_prediction"
    assert rt1.service_date == "2026-08-25"


def test_after_midnight_maps_to_previous_service_date(tmp_path, monkeypatch):
    static_dir = tmp_path / "static"; proc = tmp_path / "proc" / "date=2026-08-25"
    static_dir.mkdir(parents=True); proc.mkdir(parents=True)
    pd.DataFrame([{"trip_id":"S","route_id":"A","direction_id":0,"service_id":"WKD"}]).to_parquet(static_dir/"trips.parquet", index=False)
    pd.DataFrame([{"trip_id":"S","stop_id":"1","stop_sequence":1,"arrival_time":"25:15:00"}]).to_parquet(static_dir/"stop_times.parquet", index=False)
    pd.DataFrame([{"service_id":"WKD","monday":1,"tuesday":1,"wednesday":1,"thursday":1,"friday":1,"saturday":0,"sunday":0,"start_date":"20260101","end_date":"20261231"}]).to_parquet(static_dir/"calendar.parquet", index=False)
    # 01:15 EDT on Aug 26 belongs to Aug 25 GTFS service day and is 25:15.
    ts = int(pd.Timestamp("2026-08-26 01:15:00", tz="America/New_York").timestamp())
    pd.DataFrame([{ "trip_id":"RT","route_id":"A","direction_id":0,"stop_id":"1","stop_sequence":1,
                    "predicted_arrival":ts,"observed_at":ts-60,"feed_name":"ACE","trip_start_date":"20260825"}]).to_parquet(proc/"trip_update_observations.parquet", index=False)
    monkeypatch.setattr(reconcile, "STATIC_GTFS_DIR", static_dir); monkeypatch.setattr(reconcile, "PROCESSED_DATA_DIR", tmp_path/"proc")
    reconcile.reconcile_date("2026-08-25")
    out = pd.read_parquet(proc/"reconciled_trips.parquet").iloc[0]
    assert out.static_trip_id == "S"
    assert out.prediction_delay_seconds == 0


def test_missing_service_date_does_not_use_inactive_schedule(synthetic_gtfs):
    reconcile.reconcile_date("2026-08-23")
    # No observations for this service date should be reconciled from Tuesday data.
    out_path = synthetic_gtfs / "date=2026-08-23" / "reconciled_trips.parquet"
    assert not out_path.exists()


def test_ambiguous_candidates_are_not_silently_assigned():
    from processing.reconcile import _candidate_matches
    ts = int(pd.Timestamp("2026-08-25 08:05:00", tz="America/New_York").timestamp())
    predictions = pd.DataFrame([{
        "trip_id":"RT", "route_id":"A", "direction_id":0, "direction":"N",
        "stop_id":"101", "stop_sequence":None, "feed_name":"ACE",
        "trip_start_date":"20260825", "schedule_relationship":None,
        "predicted_arrival":ts, "observed_at":ts-60,
    }])
    schedule = pd.DataFrame([
        {"static_trip_id":"S1","route_id":"A","stop_id":"101","direction_id":0,"stop_sequence":5,"service_id":"WKD","service_date":"2026-08-25","scheduled_arrival_seconds":8*3600},
        {"static_trip_id":"S2","route_id":"A","stop_id":"101","direction_id":0,"stop_sequence":6,"service_id":"WKD","service_date":"2026-08-25","scheduled_arrival_seconds":8*3600+10*60},
    ])
    out = _candidate_matches(predictions, schedule, "2026-08-25").iloc[0]
    assert out.match_status == "ambiguous_prediction"
    assert out.static_trip_id in {"S1", "S2"}


def test_added_service_is_not_called_a_missing_schedule_match():
    from processing.reconcile import _candidate_matches
    ts = int(pd.Timestamp("2026-08-25 08:05:00", tz="America/New_York").timestamp())
    predictions = pd.DataFrame([{
        "trip_id":"RT", "route_id":"A", "direction_id":0, "direction":"N",
        "stop_id":"101", "stop_sequence":5, "feed_name":"ACE",
        "trip_start_date":"20260825", "schedule_relationship":"ADDED",
        "predicted_arrival":ts, "observed_at":ts-60,
    }])
    schedule = pd.DataFrame(columns=["static_trip_id","route_id","stop_id","direction_id","stop_sequence","service_id","service_date","scheduled_arrival_seconds"])
    out = _candidate_matches(predictions, schedule, "2026-08-25").iloc[0]
    assert out.match_status == "added_service"
