from pathlib import Path

import pandas as pd


DATA_DIR = Path("data/processed")


def main():
    stops = pd.read_parquet(DATA_DIR / "stops.parquet")

    # Parent stations are the conceptual station entities.
    stations = (
        stops[stops["location_type"] == 1]
        [
            [
                "stop_id",
                "stop_name",
                "stop_lat",
                "stop_lon",
            ]
        ]
        .copy()
    )

    stations = stations.rename(
        columns={
            "stop_id": "station_id",
            "stop_name": "station_name",
            "stop_lat": "latitude",
            "stop_lon": "longitude",
        }
    )

    # Individual platform/directional stops.
    platforms = (
        stops[stops["parent_station"].notna()]
        [
            [
                "stop_id",
                "stop_name",
                "stop_lat",
                "stop_lon",
                "parent_station",
            ]
        ]
        .copy()
    )

    platforms = platforms.rename(
        columns={
            "stop_id": "platform_id",
            "stop_name": "platform_name",
            "stop_lat": "latitude",
            "stop_lon": "longitude",
        }
    )

    stations.to_parquet(
        DATA_DIR / "stations.parquet",
        index=False,
    )

    platforms.to_parquet(
        DATA_DIR / "platforms.parquet",
        index=False,
    )

    print(f"Stations:  {len(stations):,}")
    print(f"Platforms: {len(platforms):,}")

    print("\nExample stations:")
    print(stations.head())

    print("\nExample platforms:")
    print(platforms.head())


if __name__ == "__main__":
    main()