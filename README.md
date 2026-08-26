# NYC subway reliability pipeline

An end-to-end, $0-cost data pipeline that ingests MTA GTFS-realtime feeds,
reconciles actual train movements against the published schedule, and
surfaces subway reliability metrics (on-time %, headway variance, "ghost
trains") in a Streamlit dashboard.

## Why this exists

MTA's realtime feed data is notoriously messy: trains don't have stable
IDs, and realtime trip IDs usually don't match the static schedule's trip
IDs at all. This project's core engineering problem is reconciling "what
was scheduled" against "what actually happened" at scale — everything
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
data/raw/  (Parquet, partitioned by date/line/hour)
        |
        v
processing/parse_snapshots.py  ---- dedupe overlapping polls -> trip_updates table
        |
        v
processing/reconcile.py  ---- match realtime trips to static schedule
        |
        v
processing/metrics.py  ---- on-time %, headway variance, ghost-train rate
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
