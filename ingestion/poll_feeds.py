"""
Polls every feed listed in config/feeds.yaml, decodes the GTFS-realtime
protobuf response, and hands each parsed snapshot to storage/writer.py.

Usage:
    python -m ingestion.poll_feeds              # poll once, all feeds
    python -m ingestion.poll_feeds --loop        # poll forever on POLL_INTERVAL_SECONDS
    python -m ingestion.poll_feeds --feed ACE    # poll a single feed once (useful for testing)

This is the file cron or Airflow actually invokes.
"""
import argparse
import logging
import os
import sys
import time
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv
from google.transit import gtfs_realtime_pb2

from storage.writer import write_raw_snapshot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("poll_feeds")

load_dotenv()

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "feeds.yaml"
REQUEST_TIMEOUT_SECONDS = 15


def load_feed_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def fetch_feed(feed: dict, api_key: str | None) -> gtfs_realtime_pb2.FeedMessage | None:
    """Fetch and decode a single GTFS-RT feed. Returns None on failure
    rather than raising, so one bad feed doesn't kill the whole poll loop."""
    headers = {"x-api-key": api_key} if api_key else {}
    try:
        resp = requests.get(feed["url"], headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
        resp.raise_for_status()
    except requests.RequestException as e:
        log.error("Failed to fetch feed %s (%s): %s", feed["name"], feed["url"], e)
        return None

    message = gtfs_realtime_pb2.FeedMessage()
    try:
        message.ParseFromString(resp.content)
    except Exception as e:  # noqa: BLE001 - protobuf raises generic exceptions
        log.error("Failed to parse protobuf for feed %s: %s", feed["name"], e)
        return None

    return message


def poll_once(config: dict, api_key: str | None, only_feed: str | None = None) -> int:
    """Poll every configured feed one time. Returns the count of feeds
    successfully written."""
    written = 0
    for feed in config["feeds"]:
        if only_feed and feed["name"] != only_feed:
            continue

        message = fetch_feed(feed, api_key)
        if message is None:
            continue

        entity_count = len(message.entity)
        path = write_raw_snapshot(feed_name=feed["name"], message=message)
        log.info(
            "Wrote %s entities from feed %s -> %s", entity_count, feed["name"], path
        )
        written += 1

    return written


def main():
    parser = argparse.ArgumentParser(description="Poll MTA GTFS-realtime feeds")
    parser.add_argument("--loop", action="store_true", help="Poll continuously")
    parser.add_argument("--feed", type=str, default=None, help="Only poll this feed name")
    args = parser.parse_args()

    config = load_feed_config()
    api_key = os.getenv("MTA_API_KEY") or None
    interval = int(os.getenv("POLL_INTERVAL_SECONDS", "45"))

    if not api_key:
        log.warning(
            "No MTA_API_KEY set - most feeds work without one, but if you see "
            "consistent 401/403s, register a free key at https://api.mta.info/"
        )

    if args.loop:
        log.info("Starting continuous polling every %ss (ctrl-C to stop)", interval)
        while True:
            start = time.time()
            written = poll_once(config, api_key, args.feed)
            log.info("Poll cycle complete: %s feeds written", written)
            elapsed = time.time() - start
            sleep_for = max(0, interval - elapsed)
            time.sleep(sleep_for)
    else:
        written = poll_once(config, api_key, args.feed)
        log.info("Done. %s feeds written.", written)
        sys.exit(0 if written > 0 else 1)


if __name__ == "__main__":
    main()
