"""
Streamlit dashboard for subway reliability metrics. Reads only from
processing/metrics.py's output tables - never touches raw or reconciled
data directly, so this stays fast regardless of how much raw data has
accumulated.

Usage:
    streamlit run dashboard/app.py
"""
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb
import pandas as pd
import plotly.express as px
import streamlit as st

PROCESSED_DATA_DIR = Path(os.getenv("PROCESSED_DATA_DIR", "data/processed"))

st.set_page_config(page_title="NYC subway reliability", layout="wide")


def available_dates() -> list[str]:
    if not PROCESSED_DATA_DIR.exists():
        return []
    dates = sorted(
        [
            p.name.replace("date=", "")
            for p in PROCESSED_DATA_DIR.iterdir()
            if p.is_dir() and p.name.startswith("date=")
        ],
        reverse=True,
    )
    return dates


@st.cache_data(ttl=300)
def load_metric(date: str, filename: str) -> pd.DataFrame:
    path = PROCESSED_DATA_DIR / f"date={date}" / filename
    if not path.exists():
        return pd.DataFrame()
    return duckdb.connect().execute(f"SELECT * FROM read_parquet('{path}')").df()


# Reference thresholds shown throughout the dashboard - keep these in
# sync with processing/metrics.py's ON_TIME_THRESHOLD_SECONDS if you
# change it there.
ON_TIME_TARGET_PCT = 90  # MTA's own public benchmark, roughly
GHOST_WARNING_PCT = 10   # above this, likely a feed/matching issue worth investigating


def color_for_on_time(pct: float) -> str:
    """Green/amber/red so a glance tells you good vs. bad, not just a number."""
    if pct >= ON_TIME_TARGET_PCT:
        return "#1D9E75"  # teal - meets target
    elif pct >= ON_TIME_TARGET_PCT - 15:
        return "#EF9F27"  # amber - close but under
    return "#E24B4A"  # red - well under target


def color_for_ghost(pct: float) -> str:
    return "#E24B4A" if pct >= GHOST_WARNING_PCT else "#888780"


st.title("NYC subway reliability")
st.caption(
    "Realtime vs. scheduled subway performance, computed from MTA GTFS-realtime "
    "feeds reconciled against the static schedule."
)

with st.expander("How to read this dashboard"):
    st.markdown(
        f"""
- **On-time %**: share of arrivals within 5 minutes of the scheduled time.
  Green = at or above {ON_TIME_TARGET_PCT}% (a reasonable target), amber = close,
  red = notably underperforming.
- **Ghost-train rate**: % of realtime predictions that never matched anything
  in the published schedule. A little of this is normal (extra service,
  schedule changes); above {GHOST_WARNING_PCT}% on a line usually means the
  matching logic needs tuning for that line, not that trains are actually missing.
- **Delay by hour**: average minutes late, by hour of day. Use this to spot
  *when* a line breaks down, not just whether it's reliable overall.
        """
    )

dates = available_dates()
if not dates:
    st.warning(
        "No processed data found yet. Run the pipeline first: "
        "`bash scripts/run_local.sh`"
    )
    st.stop()

selected_date = st.selectbox("Date", dates, index=0)

on_time_df = load_metric(selected_date, "on_time_by_line.parquet")
delay_df = load_metric(selected_date, "delay_by_hour.parquet")
ghost_df = load_metric(selected_date, "ghost_rate_by_line.parquet")

col1, col2, col3 = st.columns(3)
with col1:
    overall_on_time = (
        on_time_df["on_time_pct"].mean() if not on_time_df.empty else None
    )
    st.metric(
        "System-wide on-time %",
        f"{overall_on_time:.1f}%" if overall_on_time is not None else "n/a",
        delta=f"{overall_on_time - ON_TIME_TARGET_PCT:.1f} pts vs {ON_TIME_TARGET_PCT}% target"
        if overall_on_time is not None
        else None,
    )
with col2:
    if not on_time_df.empty:
        worst_row = on_time_df.sort_values("on_time_pct").iloc[0]
        st.metric(
            "Least reliable line today",
            worst_row["line"],
            delta=f"{worst_row['on_time_pct']:.1f}% on-time",
            delta_color="off",
        )
    else:
        st.metric("Least reliable line today", "n/a")
with col3:
    avg_ghost = ghost_df["ghost_pct"].mean() if not ghost_df.empty else None
    st.metric(
        "Avg ghost-train rate",
        f"{avg_ghost:.1f}%" if avg_ghost is not None else "n/a",
        delta="check matching logic" if (avg_ghost or 0) >= GHOST_WARNING_PCT else "normal range",
        delta_color="off",
    )

st.divider()

left, right = st.columns(2)

with left:
    st.subheader("On-time % by line")
    st.caption(f"Green = meets the {ON_TIME_TARGET_PCT}% target, red = underperforming")
    if not on_time_df.empty:
        sorted_df = on_time_df.sort_values("on_time_pct")
        colors = [color_for_on_time(v) for v in sorted_df["on_time_pct"]]
        fig = px.bar(
            sorted_df,
            x="on_time_pct",
            y="line",
            orientation="h",
            text="on_time_pct",
            labels={"on_time_pct": "On-time %", "line": "Line"},
        )
        fig.update_traces(marker_color=colors, texttemplate="%{text:.0f}%", textposition="outside")
        fig.add_vline(
            x=ON_TIME_TARGET_PCT,
            line_dash="dash",
            line_color="gray",
            annotation_text="target",
            annotation_position="top",
        )
        fig.update_layout(xaxis_range=[0, 105], margin=dict(l=0, r=20, t=20, b=0))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No on-time data for this date.")

with right:
    st.subheader("Ghost-train rate by line")
    st.caption(f"Red = above {GHOST_WARNING_PCT}%, likely worth investigating")
    if not ghost_df.empty:
        sorted_df = ghost_df.sort_values("ghost_pct", ascending=False)
        colors = [color_for_ghost(v) for v in sorted_df["ghost_pct"]]
        fig = px.bar(
            sorted_df,
            x="ghost_pct",
            y="line",
            orientation="h",
            text="ghost_pct",
            labels={"ghost_pct": "Unmatched prediction %", "line": "Line"},
        )
        fig.update_traces(marker_color=colors, texttemplate="%{text:.0f}%", textposition="outside")
        fig.update_layout(margin=dict(l=0, r=20, t=20, b=0))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No ghost-train data for this date.")

st.divider()
st.subheader("Average delay by hour of day")
st.caption(
    "One line per subway line. Hover to isolate one - with 8+ lines this gets "
    "busy, so use the legend to toggle lines on/off."
)
if not delay_df.empty:
    fig = px.line(
        delay_df.sort_values(["line", "hour_of_day"]),
        x="hour_of_day",
        y="avg_delay_minutes",
        color="line",
        labels={"hour_of_day": "Hour of day", "avg_delay_minutes": "Avg delay (min)"},
    )
    fig.add_hline(
        y=5,
        line_dash="dash",
        line_color="gray",
        annotation_text="5-min on-time threshold",
        annotation_position="top left",
    )
    fig.update_traces(mode="lines+markers", marker=dict(size=4))
    fig.update_layout(
        legend_title_text="Line",
        xaxis=dict(dtick=2, title="Hour of day (24h)"),
        margin=dict(l=0, r=0, t=20, b=0),
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No delay data for this date.")

st.divider()
st.caption(
    "On-time defined as within 5 minutes of scheduled arrival. "
    "'Ghost train' = a realtime prediction with no matching static schedule "
    "entry within a 10-minute window - see processing/reconcile.py for the "
    "matching logic and its limitations."
)