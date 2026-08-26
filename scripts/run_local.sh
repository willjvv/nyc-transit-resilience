#!/usr/bin/env bash
# Runs the full pipeline once, locally, for testing before scheduling it.
#
# Since realtime data needs to accumulate before there's anything to
# reconcile, this script:
#   1. Loads the static schedule (if not already loaded)
#   2. Polls all feeds once immediately
#   3. Polls again every 45s for 5 minutes, so there's enough raw data
#      to meaningfully exercise parse_snapshots/reconcile/metrics
#   4. Runs the processing steps against TODAY's date (not yesterday,
#      since we just generated today's data)
#
# For a real trial run with enough data for the reconciliation logic to
# be interesting, let poll_feeds.py --loop run for at least a few hours
# (ideally a full day) before running the processing steps.

set -euo pipefail
cd "$(dirname "$0")/.."

echo "== Step 1: static schedule =="
if [ ! -f "data/static_gtfs/stop_times.parquet" ]; then
  python -m ingestion.gtfs_static_loader
else
  echo "Static schedule already loaded, skipping. Delete data/static_gtfs/ to force a refresh."
fi

echo "== Step 2: quick ingestion smoke test (5 min, polling every 45s) =="
timeout 300 python -m ingestion.poll_feeds --loop || true

TODAY=$(date -u +%Y-%m-%d)

echo "== Step 3: parse snapshots for $TODAY =="
python -m processing.parse_snapshots --date "$TODAY"

echo "== Step 4: reconcile for $TODAY =="
python -m processing.reconcile --date "$TODAY"

echo "== Step 5: compute metrics for $TODAY =="
python -m processing.metrics --date "$TODAY"

echo "== Done. Launch the dashboard with: streamlit run dashboard/app.py =="
