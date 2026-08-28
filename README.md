# NYC subway reliability pipeline

An end-to-end, $0-cost data pipeline that ingests MTA GTFS-realtime feeds,
reconciles MTA realtime arrival predictions against the active published schedule, and
surfaces prediction-based subway reliability metrics (on-time %, prediction delay,
reconciliation quality) in a Streamlit dashboard.

## Why this exists

MTA's realtime feed data is notoriously messy: trains don't have stable
IDs, and realtime trip IDs usually don't match the static schedule's trip
IDs at all. This project's core engineering problem is reconciling "what
was scheduled" against "what the realtime feed predicted" at scale — everything
else (ingestion, storage, dashboarding) exists to feed that reconciliation
step.

## Architecture

```
MTA GTFS-RT feeds (free)
        |
        v
ingestion/poll_feeds.py  ---- polls every 30-60s, writes raw protobuf snapshots
        |
        v
data/raw/  (Parquet, partitioned by UTC date/feed/hour)
        |
        v
processing/parse_snapshots.py  ---- preserve prediction history + terminal prediction table
        |
        v
processing/reconcile.py  ---- match realtime trips to static schedule
        |
        v
processing/metrics.py  ---- prediction-based on-time %, delay, reconciliation quality
        |
        v
dashboard/app.py  (Streamlit, reads processed Parquet via DuckDB)
```

Everything runs on free tiers: your own machine or an Oracle Cloud Free
Tier VM for compute, local disk or Cloudflare R2 (10GB free) for storage,
DuckDB/Spark-local for processing, cron or self-hosted Airflow for
scheduling, Streamlit for the dashboard.

## Setup

1. **Get an MTA API key** (optional but recommended): register at
   https://api.mta.info/. Most GTFS-RT feeds no longer strictly require a
   key, but having one avoids rate-limit ambiguity.

2. **Install dependencies**

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Configure environment**

   ```bash
   cp .env.example .env
   # edit .env and add your MTA_API_KEY if you have one
   ```

4. **Load the static schedule** (do this once, and re-run whenever MTA
   publishes a schedule update — roughly monthly)

   ```bash
   python -m ingestion.gtfs_static_loader
   ```

5. **Run the pipeline once locally** to make sure everything works end to
   end before scheduling it:

   ```bash
   bash scripts/run_local.sh
   ```

6. **Launch the dashboard**

   ```bash
   streamlit run dashboard/app.py
   ```

## Running continuously

Two options, pick one:

- **cron** (simple): see `orchestration/crontab.txt` for the lines to add
  via `crontab -e`. Good enough for a solo project.
- **Airflow** (more "real" data-engineering setup, more portfolio value):
  see `orchestration/dags/subway_pipeline_dag.py`. Requires
  `pip install apache-airflow` and `airflow standalone` to run locally.

See `scripts/setup_vm.sh` for a one-shot provisioning script for an
Oracle Cloud Free Tier VM (or any Ubuntu box), including an optional
Cloudflare Tunnel so you can share the dashboard publicly for free.

## Project layout

See inline docstrings in each file. Short version:

- `ingestion/` — talks to the MTA, writes raw snapshots
- `storage/` — where/how raw and processed data get persisted
- `processing/` — cleans raw snapshots, reconciles against schedule, computes metrics
- `orchestration/` — cron and Airflow definitions to run the above on a schedule
- `dashboard/` — Streamlit app
- `data/` — local data lake (gitignored except for `.gitkeep`)
- `tests/` — unit tests, focused on the reconciliation logic

## Build order (if extending this)

1. Static GTFS loader — confirm you can query the schedule
2. Single-feed ingestion — get one line's protobuf parsing solid
3. Full ingestion across all lines, running under cron for a few days
4. Snapshot parsing/dedup
5. Reconciliation logic (the hard part — budget the most time here)
6. Metrics + dashboard
7. Orchestration + deployment


## Measurement semantics

The realtime source used here is GTFS-realtime TripUpdates. Those records provide predicted arrival/departure times; they are not treated as authoritative observed arrival timestamps. The pipeline therefore reports **prediction delay** (final observed prediction minus scheduled arrival) and retains the full prediction history for later forecast-quality analysis.

The data model keeps `feed_name` separate from `route_id`: a feed such as `ACE` contains multiple subway lines, while `route_id` identifies the individual route. Daily metrics group by `route_id`.

Reconciliation first filters static trips by the requested service date using `calendar` and optional `calendar_dates`, then compares local New York service-day seconds. Predictions with weak or competing candidates are marked `ambiguous_prediction` rather than being silently assigned. Explicit GTFS-realtime added/duplicated service can be classified separately.

The network graph contains only consecutive stops actually served by a scheduled trip. Edge distance is median scheduled running time; service frequency is metadata, not a shortest-path distance. Transfers are represented by normalized station nodes rather than route-wide shortcut edges.


### Rebuilding existing data after this refactor

Previously generated `trip_updates`, `reconciled_trips`, and dashboard metric Parquets were built under the old feed/UTC/matching semantics. Regenerate them from the raw snapshots after updating this version; do not mix old processed artifacts with the new metrics. The static schedule should also be refreshed so `calendar_dates.parquet` is available when the MTA bundle provides service exceptions.
