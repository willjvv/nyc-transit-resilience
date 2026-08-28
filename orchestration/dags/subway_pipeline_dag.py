"""
Airflow DAG for the NYC subway pipeline. Use this instead of cron if you
want retries, task-level monitoring, and a visual DAG graph - more
setup overhead, but better portfolio value if you're demonstrating data
engineering skills specifically.

Requires: pip install apache-airflow
Run locally with: airflow standalone
Then copy/symlink this file into your $AIRFLOW_HOME/dags directory (or
point AIRFLOW__CORE__DAGS_FOLDER at orchestration/dags/).

Note: ingestion (poll_feeds --loop) is intentionally NOT run inside this
DAG - polling every 30-60s is a long-running process, not a scheduled
batch task, and doesn't fit Airflow's execution model well. Run
poll_feeds.py --loop as its own systemd service or background process;
this DAG only handles the daily batch processing steps.
"""
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

default_args = {
    "owner": "subway-pipeline",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="subway_pipeline",
    default_args=default_args,
    description="Daily batch processing: parse -> reconcile -> metrics",
    schedule_interval="10 2 * * *",  # 2:10am daily
    start_date=datetime(2026, 8, 1),
    catchup=False,
    tags=["subway", "gtfs"],
) as dag:

    parse = BashOperator(
        task_id="parse_snapshots",
        bash_command="cd {{ var.value.project_dir }} && python -m processing.parse_snapshots --date {{ ds }}",
    )

    reconcile = BashOperator(
        task_id="reconcile",
        bash_command="cd {{ var.value.project_dir }} && python -m processing.reconcile --date {{ ds }}",
    )

    metrics = BashOperator(
        task_id="compute_metrics",
        bash_command="cd {{ var.value.project_dir }} && python -m processing.metrics --date {{ ds }}",
    )

    parse >> reconcile >> metrics

# Set the project_dir Airflow Variable before running:
#   airflow variables set project_dir /home/ubuntu/nyc-subway-pipeline
