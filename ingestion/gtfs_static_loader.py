"""
Downloads and unpacks MTA's static GTFS schedule bundle (routes, trips,
stop_times, stops, calendar) into data/static_gtfs/ as Parquet tables.

This is your ground truth for "what was scheduled" - reconcile.py joins
against these tables. MTA updates the static schedule periodically
(roughly monthly, more often around service changes), so re-run this
job on a similar cadence.

Usage:
    python -m ingestion.gtfs_static_loader
"""
import csv
import io
import logging
import os
import zipfile
from pathlib import Path

import pandas as pd
import requests
import yaml
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gtfs_static_loader")

load_dotenv()

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "feeds.yaml"
STATIC_DIR = Path(os.getenv("STATIC_GTFS_DIR", "data/static_gtfs"))

# The GTFS tables we actually need for reconciliation. GTFS bundles
# contain more files than this (fare_rules, shapes, etc) - skip what
# we don't use to keep this fast and the output small.
TABLES_TO_LOAD = ["routes", "trips", "stop_times", "stops", "calendar"]


def download_static_bundle(url: str) -> zipfile.ZipFile:
    log.info("Downloading static GTFS bundle from %s", url)
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    return zipfile.ZipFile(io.BytesIO(resp.content))


def load_table_from_zip(zf: zipfile.ZipFile, table_name: str) -> pd.DataFrame | None:
    filename = f"{table_name}.txt"
    if filename not in zf.namelist():
        log.warning("%s not present in this GTFS bundle, skipping", filename)
        return None
    with zf.open(filename) as f:
        # GTFS files are plain CSV with a header row
        reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
        rows = list(reader)
    return pd.DataFrame(rows)


def main():
    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)

    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    zf = download_static_bundle(config["static_gtfs_url"])

    for table_name in TABLES_TO_LOAD:
        df = load_table_from_zip(zf, table_name)
        if df is None:
            continue
        out_path = STATIC_DIR / f"{table_name}.parquet"
        df.to_parquet(out_path, index=False)
        log.info("Wrote %s rows to %s", len(df), out_path)

    log.info("Static GTFS load complete. Tables in %s", STATIC_DIR)


if __name__ == "__main__":
    main()
