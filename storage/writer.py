"""
Handles writing raw GTFS-RT snapshots to the data lake.

Layout: data/raw/date=YYYY-MM-DD/line=<feed_name>/hour=HH/snapshot_<ts>.parquet

Partitioning by date/line/hour lets processing/parse_snapshots.py (and
DuckDB/Spark queries in general) prune to just the files they need
instead of scanning everything.

If R2 credentials are present in the environment, snapshots are also
uploaded off-box after being written locally - local disk is always the
source of truth, R2 is best-effort durability.
"""
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from google.protobuf.json_format import MessageToDict

load_dotenv()

RAW_DATA_DIR = Path(os.getenv("RAW_DATA_DIR", "data/raw"))


def _feed_message_to_dataframe(message) -> pd.DataFrame:
    """Flatten a GTFS-RT FeedMessage into a flat table: one row per
    entity (trip update or vehicle position), with the nested protobuf
    fields kept as a JSON-serializable dict column for now. Real
    flattening of stop_time_update arrays happens in
    processing/parse_snapshots.py - this layer just needs to capture
    everything losslessly.
    """
    as_dict = MessageToDict(message, preserving_proto_field_name=True)
    entities = as_dict.get("entity", [])

    rows = []
    feed_timestamp = as_dict.get("header", {}).get("timestamp")
    for entity in entities:
        rows.append(
            {
                "entity_id": entity.get("id"),
                "feed_timestamp": feed_timestamp,
                "trip_update": entity.get("trip_update"),
                "vehicle": entity.get("vehicle"),
                "alert": entity.get("alert"),
            }
        )

    return pd.DataFrame(rows)


def write_raw_snapshot(feed_name: str, message) -> str:
    """Write one polled snapshot to the partitioned raw data lake.
    Returns the path written to."""
    now = datetime.now(timezone.utc)
    partition_dir = (
        RAW_DATA_DIR
        / f"date={now:%Y-%m-%d}"
        / f"line={feed_name}"
        / f"hour={now:%H}"
    )
    partition_dir.mkdir(parents=True, exist_ok=True)

    filename = f"snapshot_{now:%H%M%S}.parquet"
    out_path = partition_dir / filename

    df = _feed_message_to_dataframe(message)
    # Store nested fields as JSON strings - Parquet can't natively hold
    # arbitrary nested Python dicts from protobuf without a schema, and
    # we want this write to never fail regardless of feed structure.
    for col in ("trip_update", "vehicle", "alert"):
        if col in df.columns:
            df[col] = df[col].apply(lambda v: str(v) if v is not None else None)

    df.to_parquet(out_path, index=False)

    _maybe_upload_to_r2(out_path)

    return str(out_path)


def _maybe_upload_to_r2(local_path: Path) -> None:
    """Best-effort upload to Cloudflare R2 if credentials are configured.
    Silently skips if not configured - local disk is the source of
    truth, R2 is optional off-box durability."""
    if not os.getenv("R2_ACCESS_KEY_ID"):
        return

    try:
        import boto3

        client = boto3.client(
            "s3",
            endpoint_url=f"https://{os.getenv('R2_ACCOUNT_ID')}.r2.cloudflarestorage.com",
            aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
        )
        key = str(local_path.relative_to(RAW_DATA_DIR.parent))
        client.upload_file(str(local_path), os.getenv("R2_BUCKET_NAME"), key)
    except Exception as e:  # noqa: BLE001
        # Never let an upload failure break ingestion - local write already succeeded.
        import logging

        logging.getLogger("storage.writer").warning("R2 upload failed: %s", e)
