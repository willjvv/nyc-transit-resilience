import pandas as pd

from processing.network_analysis import build_subway_graph


def test_network_only_connects_consecutive_stops_and_uses_travel_time_distance():
    stops = pd.DataFrame([
        {"stop_id":"A1","stop_name":"A","parent_station":"SA","stop_lat":1,"stop_lon":1,"location_type":0},
        {"stop_id":"B1","stop_name":"B","parent_station":"SB","stop_lat":2,"stop_lon":2,"location_type":0},
        {"stop_id":"C1","stop_name":"C","parent_station":"SC","stop_lat":3,"stop_lon":3,"location_type":0},
    ])
    trips = pd.DataFrame([
        {"trip_id":"T1","route_id":"A"},
        {"trip_id":"T2","route_id":"A"},
        {"trip_id":"T3","route_id":"A"},
    ])
    stop_times = pd.DataFrame([
        {"trip_id":"T1","stop_id":"A1","stop_sequence":1,"arrival_time":"08:00:00"},
        {"trip_id":"T1","stop_id":"B1","stop_sequence":2,"arrival_time":"08:02:00"},
        {"trip_id":"T1","stop_id":"C1","stop_sequence":3,"arrival_time":"08:05:00"},
        {"trip_id":"T2","stop_id":"A1","stop_sequence":1,"arrival_time":"09:00:00"},
        {"trip_id":"T2","stop_id":"B1","stop_sequence":2,"arrival_time":"09:02:30"},
        {"trip_id":"T2","stop_id":"C1","stop_sequence":3,"arrival_time":"09:05:30"},
        {"trip_id":"T3","stop_id":"C1","stop_sequence":1,"arrival_time":"10:00:00"},
        {"trip_id":"T3","stop_id":"B1","stop_sequence":2,"arrival_time":"10:03:00"},
        {"trip_id":"T3","stop_id":"A1","stop_sequence":3,"arrival_time":"10:05:00"},
    ])
    graph = build_subway_graph(stops, stop_times, trips)
    assert set(graph.nodes) == {"SA", "SB", "SC"}
    assert set(graph.edges) == {("SA", "SB"), ("SB", "SC")}
    assert ("SA", "SC") not in graph.edges
    assert graph["SA"]["SB"]["travel_time_seconds"] == 120.0
    assert graph["SA"]["SB"]["scheduled_trip_count"] == 3
