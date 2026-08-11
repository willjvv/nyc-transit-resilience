from pathlib import Path

import pandas as pd


RAW_DIR = Path("data/raw")
PROCESSED_DIR = Path("data/processed")


GTFS_FILES = [
    "agency.txt",
    "calendar.txt",
    "calendar_dates.txt",
    "routes.txt",
    "shapes.txt",
    "stop_times.txt",
    "stops.txt",
    "transfers.txt",
    "trips.txt",
]


def load_gtfs_file(filename: str) -> pd.DataFrame:
    path = RAW_DIR / filename

    if not path.exists():
        raise FileNotFoundError(f"Missing GTFS file: {path}")

    return pd.read_csv(path)


def main():
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    for filename in GTFS_FILES:
        print(f"Loading {filename}...")

        df = load_gtfs_file(filename)

        output_name = Path(filename).with_suffix(".parquet")

        df.to_parquet(
            PROCESSED_DIR / output_name,
            index=False,
        )

        print(f"  Rows: {len(df):,}")
        print(f"  Columns: {len(df.columns)}")

    print("\nGTFS ingestion complete.")


if __name__ == "__main__":
    main()