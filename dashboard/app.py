"""
Streamlit dashboard for subway reliability metrics. Reads only from
processing/metrics.py's output tables - never touches raw or reconciled
data directly, so this stays fast regardless of how much raw data has
accumulated.

Usage:
    streamlit run dashboard/app.py
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb
import pandas as pd
import plotly.express as px
import streamlit as st

# Add dashboard directory to path for imports
dashboard_dir = Path(__file__).parent
sys.path.insert(0, str(dashboard_dir))

from explanations import (
    COLOR_EXPLANATIONS,
    FAQ,
    METRIC_EXPLANATIONS,
    ONBOARDING,
    THRESHOLDS,
    get_color_explanation,
    get_context,
    get_explanation,
)

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

# View toggle
view_mode = st.radio(
    "View Mode",
    ["Simple View", "Advanced View"],
    horizontal=True,
    help="Simple View focuses on key metrics for daily commuters. Advanced View includes detailed analysis for power users."
)

# Onboarding section (collapsible)
with st.expander("📖 What is this dashboard?"):
    st.markdown(ONBOARDING["what_is_this"]["content"])
    st.markdown(ONBOARDING["data_source"]["content"])
    st.markdown(ONBOARDING["how_to_use"]["content"])

# FAQ section (collapsible)
with st.expander("❓ Frequently Asked Questions"):
    for item in FAQ:
        st.markdown(f"**Q: {item['question']}**")
        st.markdown(item['answer'])
        st.markdown("---")

# Simple view specific help
if view_mode == "Simple View":
    st.info("💡 **Simple View** shows the key metrics that matter most for daily commuters. Switch to Advanced View for detailed analysis.")

# Legacy help text for advanced view
if view_mode == "Advanced View":
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

# Data freshness indicator
try:
    selected_dt = datetime.strptime(selected_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    today = datetime.now(timezone.utc)
    days_ago = (today.date() - selected_dt.date()).days
    if days_ago == 0:
        freshness = "🟢 Today's data"
    elif days_ago == 1:
        freshness = "🟡 Yesterday's data"
    else:
        freshness = f"🔴 {days_ago} days old"
    st.caption(f"Data freshness: {freshness}")
except:
    st.caption("Data freshness: Unknown")

on_time_df = load_metric(selected_date, "on_time_by_line.parquet")
delay_df = load_metric(selected_date, "delay_by_hour.parquet")
ghost_df = load_metric(selected_date, "ghost_rate_by_line.parquet")

# Color coding legend
st.markdown("### Performance Legend")
col_legend = st.columns(3)
with col_legend[0]:
    st.markdown(f"{COLOR_EXPLANATIONS['green']['emoji']} **Good** - {COLOR_EXPLANATIONS['green']['meaning']}")
with col_legend[1]:
    st.markdown(f"{COLOR_EXPLANATIONS['amber']['emoji']} **Acceptable** - {COLOR_EXPLANATIONS['amber']['meaning']}")
with col_legend[2]:
    st.markdown(f"{COLOR_EXPLANATIONS['red']['emoji']} **Poor** - {COLOR_EXPLANATIONS['red']['meaning']}")
st.divider()

# Main metrics section
if view_mode == "Simple View":
    # Simple view: Focus on 3 key metrics for riders
    st.markdown("### 🚇 Key Metrics for Today's Commute")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        overall_on_time = (
            on_time_df["on_time_pct"].mean() if not on_time_df.empty else None
        )
        emoji = COLOR_EXPLANATIONS['green']['emoji'] if overall_on_time and overall_on_time >= ON_TIME_TARGET_PCT else (
            COLOR_EXPLANATIONS['amber']['emoji'] if overall_on_time and overall_on_time >= ON_TIME_TARGET_PCT - 15 else COLOR_EXPLANATIONS['red']['emoji']
        )
        st.metric(
            f"{emoji} Trains On Schedule",
            f"{overall_on_time:.1f}%" if overall_on_time is not None else "n/a",
            delta=f"{overall_on_time - ON_TIME_TARGET_PCT:.1f} pts vs {ON_TIME_TARGET_PCT}% target"
            if overall_on_time is not None
            else None,
            help=get_explanation("on_time_performance", "simple")
        )
        if overall_on_time is not None:
            st.caption(get_context("on_time_performance"))
    
    with col2:
        if not on_time_df.empty:
            worst_row = on_time_df.sort_values("on_time_pct").iloc[0]
            best_row = on_time_df.sort_values("on_time_pct", ascending=False).iloc[0]
            st.metric(
                "Most Reliable Line",
                best_row["line"],
                delta=f"{best_row['on_time_pct']:.1f}% on-time",
                delta_color="normal",
                help=get_explanation("reliable_lines", "simple")
            )
        else:
            st.metric("Most Reliable Line", "n/a")
    
    with col3:
        if not on_time_df.empty:
            avg_delay = on_time_df["avg_delay_minutes"].mean()
            delay_emoji = COLOR_EXPLANATIONS['green']['emoji'] if avg_delay <= THRESHOLDS['delay_good'] else (
                COLOR_EXPLANATIONS['amber']['emoji'] if avg_delay <= THRESHOLDS['delay_concern'] else COLOR_EXPLANATIONS['red']['emoji']
            )
            st.metric(
                f"{delay_emoji} Average Delay",
                f"{avg_delay:.1f} min" if not pd.isna(avg_delay) else "n/a",
                delta="normal" if avg_delay <= THRESHOLDS['delay_good'] else "elevated",
                delta_color="normal" if avg_delay <= THRESHOLDS['delay_good'] else "inverse",
                help=get_explanation("average_delay", "simple")
            )
            if not pd.isna(avg_delay):
                st.caption(get_context("average_delay"))
        else:
            st.metric("Average Delay", "n/a")
    
    st.divider()
    st.markdown("### 📊 Line-by-Line Performance")
    
    # Simplified on-time chart for simple view
    if not on_time_df.empty:
        sorted_df = on_time_df.sort_values("on_time_pct")
        colors = [color_for_on_time(v) for v in sorted_df["on_time_pct"]]
        emojis = [COLOR_EXPLANATIONS['green']['emoji'] if v >= ON_TIME_TARGET_PCT else (
            COLOR_EXPLANATIONS['amber']['emoji'] if v >= ON_TIME_TARGET_PCT - 15 else COLOR_EXPLANATIONS['red']['emoji']
        ) for v in sorted_df["on_time_pct"]]
        
        # Add emoji to line names
        sorted_df = sorted_df.copy()
        sorted_df['line_with_emoji'] = [f"{emoji} {line}" for emoji, line in zip(emojis, sorted_df['line'])]
        
        fig = px.bar(
            sorted_df,
            x="on_time_pct",
            y="line_with_emoji",
            orientation="h",
            text="on_time_pct",
            labels={"on_time_pct": "On-time %", "line_with_emoji": "Line"},
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
        st.caption("Green bars meet the 90% on-time target. Hover over bars for exact percentages.")
    else:
        st.info("No on-time data for this date.")

else:
    # Advanced view: All current metrics
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
            help=get_explanation("on_time_performance", "detailed")
        )
    with col2:
        if not on_time_df.empty:
            worst_row = on_time_df.sort_values("on_time_pct").iloc[0]
            st.metric(
                "Least reliable line today",
                worst_row["line"],
                delta=f"{worst_row['on_time_pct']:.1f}% on-time",
                delta_color="off",
                help=get_explanation("reliable_lines", "detailed")
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
            help=get_explanation("ghost_trains", "detailed")
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