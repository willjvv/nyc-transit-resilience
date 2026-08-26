"""Raw GTFS-realtime snapshot writer.

Partitioning is by UTC ingestion date/feed/hour. ``feed_name`` and the feed
header timestamp are stored explicitly; a feed grouping is not a subway line.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from google.protobuf.json_format import MessageToDict

load_dotenv()
RAW_DATA_DIR = Path(os.getenv("RAW_DATA_DIR", "data/raw"))
log = logging.getLogger("storage.writer")


def _feed_message_to_dataframe(message, feed_name: str) -> pd.DataFrame:
    as_dict = MessageToDict(message, preserving_proto_field_name=True)
    entities = as_dict.get("entity", [])
    feed_timestamp = as_dict.get("header", {}).get("timestamp")
    fetched_at = int(datetime.now(timezone.utc).timestamp())
    rows = []
    for entity in entities:
        rows.append(
            {
                "entity_id": entity.get("id"),
                "feed_name": feed_name,
                "feed_timestamp": feed_timestamp,
                "fetched_at": fetched_at,
                "trip_update": json.dumps(entity.get("trip_update")) if entity.get("trip_update") is not None else None,
                "vehicle": json.dumps(entity.get("vehicle")) if entity.get("vehicle") is not None else None,
                "alert": json.dumps(entity.get("alert")) if entity.get("alert") is not None else None,
            }
        )
    return pd.DataFrame(rows)


def write_raw_snapshot(feed_name: str, message) -> str:
    now = datetime.now(timezone.utc)
    partition_dir = (
        RAW_DATA_DIR / f"date={now:%Y-%m-%d}" / f"feed={feed_name}" / f"hour={now:%H}"
    )
    partition_dir.mkdir(parents=True, exist_ok=True)
    filename = f"snapshot_{now:%Y%m%dT%H%M%S.%fZ}.parquet"
    out_path = partition_dir / filename
    _feed_message_to_dataframe(message, feed_name).to_parquet(out_path, index=False)
    _maybe_upload_to_r2(out_path)
    return str(out_path)


def _maybe_upload_to_r2(local_path: Path) -> None:
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
    except Exception as exc:  # noqa: BLE001
        log.warning("R2 upload failed: %s", exc)
