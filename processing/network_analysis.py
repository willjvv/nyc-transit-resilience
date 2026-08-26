"""Build a physically meaningful station graph from static GTFS.

Nodes are normalized stations (parent_station where available). Edges are only
between consecutive stops actually served by a scheduled trip. Edge distance is
median scheduled in-vehicle running time in seconds; service frequency is an
attribute, not a distance multiplier. Transfer behavior is represented by shared
station nodes rather than by inventing route-wide shortcuts.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import networkx as nx
import pandas as pd

from processing.time_utils import parse_gtfs_time

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("network_analysis")

STATIC_GTFS_DIR = Path(os.getenv("STATIC_GTFS_DIR", "data/static_gtfs"))
PROCESSED_DATA_DIR = Path(os.getenv("PROCESSED_DATA_DIR", "data/processed"))


def load_gtfs_data():
    stops = pd.read_parquet(STATIC_GTFS_DIR / "stops.parquet")
    stop_times = pd.read_parquet(STATIC_GTFS_DIR / "stop_times.parquet")
    trips = pd.read_parquet(STATIC_GTFS_DIR / "trips.parquet")
    routes = pd.read_parquet(STATIC_GTFS_DIR / "routes.parquet")
    return stops, stop_times, trips, routes


def normalize_station_ids(stops: pd.DataFrame) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for _, row in stops.iterrows():
        stop_id = str(row["stop_id"])
        parent = row.get("parent_station")
        mapping[stop_id] = str(parent) if pd.notna(parent) and str(parent) else stop_id
    return mapping


def _station_metadata(stops: pd.DataFrame, station_mapping: dict[str, str]) -> dict[str, dict]:
    metadata: dict[str, dict] = {}
    for _, row in stops.iterrows():
        normalized = station_mapping[str(row["stop_id"])]
        if normalized in metadata:
            continue
        metadata[normalized] = {
            "stop_name": row.get("stop_name"),
            "stop_lat": row.get("stop_lat"),
            "stop_lon": row.get("stop_lon"),
            "location_type": row.get("location_type"),
        }
    return metadata


def build_subway_graph(stops: pd.DataFrame, stop_times: pd.DataFrame, trips: pd.DataFrame) -> nx.Graph:
    """Construct an undirected station graph from actual consecutive stop pairs."""
    mapping = normalize_station_ids(stops)
    metadata = _station_metadata(stops, mapping)
    G = nx.Graph()
    for station_id, attrs in metadata.items():
        G.add_node(station_id, **attrs)

    trip_cols = [c for c in ["trip_id", "route_id", "direction_id"] if c in trips.columns]
    timed = stop_times.merge(trips[trip_cols], on="trip_id", how="inner")
    timed["stop_sequence"] = pd.to_numeric(timed.get("stop_sequence"), errors="coerce")
    timed["arrival_seconds"] = timed["arrival_time"].map(parse_gtfs_time)
    timed["departure_seconds"] = timed.get("departure_time", timed["arrival_time"]).map(parse_gtfs_time)
    timed = timed.dropna(subset=["stop_sequence", "arrival_seconds", "departure_seconds", "route_id"])
    timed["arrival_seconds"] = timed["arrival_seconds"].astype(int)
    timed["departure_seconds"] = timed["departure_seconds"].astype(int)
    timed = timed.sort_values(["trip_id", "stop_sequence"])

    edge_records: list[dict] = []
    for trip_id, trip_stops in timed.groupby("trip_id", sort=False):
        trip_stops = trip_stops.reset_index(drop=True)
        for i in range(len(trip_stops) - 1):
            a, b = trip_stops.iloc[i], trip_stops.iloc[i + 1]
            from_station = mapping[str(a.stop_id)]
            to_station = mapping[str(b.stop_id)]
            if from_station == to_station:
                continue
            runtime = int(b.arrival_seconds) - int(a.departure_seconds)
            if runtime <= 0:
                continue
            u, v = sorted((from_station, to_station))
            edge_records.append(
                {
                    "from_station": u,
                    "to_station": v,
                    "route_id": str(a.route_id),
                    "runtime_seconds": runtime,
                    "trip_id": trip_id,
                }
            )

    if not edge_records:
        return G

    edge_df = pd.DataFrame(edge_records)
    grouped = edge_df.groupby(["from_station", "to_station"], sort=False)
    for (u, v), group in grouped:
        route_ids = sorted(group["route_id"].dropna().unique().tolist())
        G.add_edge(
            u,
            v,
            travel_time_seconds=float(group["runtime_seconds"].median()),
            route_ids=route_ids,
            route_count=len(route_ids),
            scheduled_trip_count=int(group["trip_id"].nunique()),
            edge_type="consecutive_stops",
        )

    # Station-level transfer semantics: a normalized station is a single node.
    # Record the number of routes serving it rather than adding route-wide edges.
    station_routes = {}
    for stop_id, route_id in timed[["stop_id", "route_id"]].drop_duplicates().itertuples(index=False):
        station = mapping[str(stop_id)]
        station_routes.setdefault(station, set()).add(str(route_id))
    for station, route_ids in station_routes.items():
        if station in G.nodes:
            G.nodes[station]["routes_served"] = sorted(route_ids)
            G.nodes[station]["route_count"] = len(route_ids)

    log.info("Graph built: %d stations, %d consecutive-stop edges", G.number_of_nodes(), G.number_of_edges())
    return G


def calculate_centrality_metrics(G: nx.Graph):
    log.info("Calculating centrality metrics using scheduled travel time as edge distance")
    return {
        "betweenness": nx.betweenness_centrality(G, weight="travel_time_seconds"),
        "degree": nx.degree_centrality(G),
        "closeness": nx.closeness_centrality(G, distance="travel_time_seconds"),
        "eigenvector": nx.eigenvector_centrality(G, max_iter=1000, weight=None),
    }


def identify_critical_stations(G: nx.Graph, centrality_metrics, top_n: int = 50) -> pd.DataFrame:
    rows = []
    for node in G.nodes:
        attrs = G.nodes[node]
        rows.append(
            {
                "station_id": node,
                "stop_name": attrs.get("stop_name"),
                "stop_lat": attrs.get("stop_lat"),
                "stop_lon": attrs.get("stop_lon"),
                "betweenness_centrality": centrality_metrics["betweenness"].get(node, 0.0),
                "degree_centrality": centrality_metrics["degree"].get(node, 0.0),
                "closeness_centrality": centrality_metrics["closeness"].get(node, 0.0),
                "eigenvector_centrality": centrality_metrics["eigenvector"].get(node, 0.0),
                "degree": G.degree(node),
                "route_count": attrs.get("route_count", 0),
                "routes_served": attrs.get("routes_served", []),
            }
        )
    df = pd.DataFrame(rows)
    for metric in ["betweenness_centrality", "degree_centrality", "closeness_centrality", "eigenvector_centrality"]:
        lo, hi = df[metric].min(), df[metric].max()
        df[f"{metric}_normalized"] = 0.0 if hi == lo else (df[metric] - lo) / (hi - lo)
    df["combined_score"] = (
        0.4 * df["betweenness_centrality_normalized"]
        + 0.2 * df["degree_centrality_normalized"]
        + 0.2 * df["closeness_centrality_normalized"]
        + 0.2 * df["eigenvector_centrality_normalized"]
    )
    df = df.sort_values(["combined_score", "stop_name"], ascending=[False, True]).reset_index(drop=True)
    df["rank"] = range(1, len(df) + 1)
    return df.head(top_n)


def export_critical_stations(df: pd.DataFrame, output_path=None):
    output_path = output_path or PROCESSED_DATA_DIR / "critical_stations.parquet"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_path, index=False)
    return output_path


def main():
    stops, stop_times, trips, _routes = load_gtfs_data()
    graph = build_subway_graph(stops, stop_times, trips)
    metrics = calculate_centrality_metrics(graph)
    critical = identify_critical_stations(graph, metrics)
    path = export_critical_stations(critical)
    log.info("Exported critical stations to %s", path)


if __name__ == "__main__":
    main()
