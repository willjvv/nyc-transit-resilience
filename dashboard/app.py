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
from zoneinfo import ZoneInfo

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
    "MTA GTFS-realtime arrival predictions reconciled against the active static schedule."
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
- **Prediction matching issue rate**: % of terminal realtime predictions that are
  unmatched or ambiguous against the active schedule. Extra service and schedule
  changes can be legitimate; elevated values are primarily a data-quality signal.
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
    from processing.time_utils import NY_TZ
    # Service dates are New York local dates, not UTC dates
    selected_dt = datetime.strptime(selected_date, "%Y-%m-%d").replace(tzinfo=NY_TZ)
    today = datetime.now(NY_TZ)
    days_ago = (today.date() - selected_dt.date()).days
    if days_ago == 0:
        freshness = "🟢 Today's data"
    elif days_ago == 1:
        freshness = "🟡 Yesterday's data"
    else:
        freshness = f"🔴 {days_ago} days old"
    st.caption(f"Data freshness: {freshness}")
except Exception as e:
    st.caption(f"Data freshness: Unknown (error: {e})")

on_time_df = load_metric(selected_date, "on_time_by_line.parquet")
delay_df = load_metric(selected_date, "delay_by_hour.parquet")
ghost_df = load_metric(selected_date, "prediction_quality_by_line.parquet")
if ghost_df.empty:
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
            100.0 * on_time_df["on_time_count"].sum() / on_time_df["matched_count"].sum()
            if not on_time_df.empty and on_time_df["matched_count"].sum() else None
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
            avg_delay = (
                (on_time_df["avg_delay_minutes"] * on_time_df["matched_count"]).sum()
                / on_time_df["matched_count"].sum()
                if on_time_df["matched_count"].sum() else float("nan")
            )
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
            100.0 * on_time_df["on_time_count"].sum() / on_time_df["matched_count"].sum()
            if not on_time_df.empty and on_time_df["matched_count"].sum() else None
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
        avg_ghost = (
            100.0 * ghost_df["unmatched_count"].add(ghost_df["ambiguous_count"]).sum()
            / ghost_df["total_predictions"].sum()
            if not ghost_df.empty and ghost_df["total_predictions"].sum() else None
        )
        st.metric(
            "Avg unmatched/ambiguous rate",
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
        st.subheader("Unmatched/ambiguous predictions by line")
        st.caption(f"Red = above {GHOST_WARNING_PCT}%, likely worth investigating")
        if not ghost_df.empty:
            quality_col = "data_quality_issue_pct" if "data_quality_issue_pct" in ghost_df.columns else "ghost_pct"
            sorted_df = ghost_df.sort_values(quality_col, ascending=False)
            colors = [color_for_ghost(v) for v in sorted_df[quality_col]]
            fig = px.bar(
                sorted_df,
                x=quality_col,
                y="line",
                orientation="h",
                text=quality_col,
                labels={quality_col: "Prediction matching issue %", "line": "Line"},
            )
            fig.update_traces(marker_color=colors, texttemplate="%{text:.0f}%", textposition="outside")
            fig.update_layout(margin=dict(l=0, r=20, t=20, b=0))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No prediction-quality data for this date.")

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

    # Network Resilience Section
    st.subheader("🌐 Network Resilience Analysis")
    st.caption("System-wide connectivity and critical station analysis")

    # Add network resilience onboarding
    with st.expander("📖 Understanding Network Resilience"):
        st.markdown(ONBOARDING["network_resilience_info"]["content"])

    # Load critical stations data
    critical_stations_path = PROCESSED_DATA_DIR / "critical_stations.parquet"
    if critical_stations_path.exists():
        critical_df = pd.read_parquet(critical_stations_path)

        # Map visualization
        st.markdown("### 🗺️ Critical Stations Map")
        st.caption("Station size and color indicate network importance (red = most critical)")

        # Centrality metric selector for visualization
        centrality_metric = st.selectbox(
            "Color stations by:",
            ["Betweenness Centrality", "Degree Centrality", "Closeness Centrality", "Combined Score"],
            help="Choose which centrality metric to visualize on the map"
        )

        metric_map = {
            "Betweenness Centrality": "betweenness_centrality",
            "Degree Centrality": "degree_centrality",
            "Closeness Centrality": "closeness_centrality",
            "Combined Score": "combined_score"
        }

        selected_metric = metric_map[centrality_metric]

        # Create map visualization
        fig_map = px.scatter_mapbox(
            critical_df,
            lat="stop_lat",
            lon="stop_lon",
            color=selected_metric,
            size="combined_score",
            hover_name="stop_name",
            hover_data={
                "rank": True,
                "routes_served": True,
                "betweenness_centrality": ":.3f",
                "degree_centrality": ":.3f",
                "route_count": True
            },
            color_continuous_scale="RdYlGn_r",  # Red (high) to Green (low)
            size_max=20,
            zoom=10,
            center={"lat": 40.7128, "lon": -74.0060},  # NYC center
            labels={
                "stop_name": "Station",
                "rank": "Criticality Rank",
                "routes_served": "Routes",
                "route_count": "Route Count",
                "betweenness_centrality": "Betweenness",
                "degree_centrality": "Degree"
            }
        )

        fig_map.update_layout(
            mapbox_style="open-street-map",
            height=500,
            margin=dict(l=0, r=0, t=30, b=0),
            coloraxis_colorbar=dict(title=centrality_metric)
        )

        st.plotly_chart(fig_map, use_container_width=True)
        st.caption("💡 Larger, redder stations are more critical for network connectivity. Hover for details.")

        st.divider()

        # Critical stations ranking table
        st.markdown("### 📊 Critical Stations Ranking")
        st.caption("Top 50 most critical stations for network connectivity")

        # Show top 50 stations
        top_stations = critical_df.head(50).copy()
        top_stations['routes_display'] = top_stations['routes_served'].apply(lambda x: ', '.join(x) if isinstance(x, list) else str(x))

        display_columns = {
            'rank': 'Rank',
            'stop_name': 'Station Name',
            'routes_display': 'Routes Served',
            'route_count': 'Route Count',
            'betweenness_centrality': 'Betweenness',
            'degree_centrality': 'Degree',
            'closeness_centrality': 'Closeness',
            'combined_score': 'Criticality Score'
        }

        display_df = top_stations[list(display_columns.keys())].rename(columns=display_columns)
        display_df = display_df.round({
            'Betweenness': 3,
            'Degree': 3,
            'Closeness': 3,
            'Criticality Score': 3
        })

        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Rank": st.column_config.NumberColumn("Rank", help="Lower rank = more critical"),
                "Criticality Score": st.column_config.NumberColumn("Score", help="Combined centrality metric"),
                "Betweenness": st.column_config.NumberColumn("Betweenness", help="Network flow importance"),
                "Degree": st.column_config.NumberColumn("Degree", help="Connection diversity"),
                "Closeness": st.column_config.NumberColumn("Closeness", help="Accessibility score")
            }
        )

        st.caption("🎯 Betweenness centrality is weighted most heavily in the criticality score.")

        # Network diagram for top stations
        st.markdown("### 🔗 Critical-Station Scatter (Top 30)")
        st.caption("Scatter view of the most central stations; use the map above for geographic context")

        if st.checkbox("Show network diagram", help="Display a network graph of the top 30 most critical stations"):
            import numpy as np
            top_30 = critical_df.head(30)

            # Create a simple network visualization using scatter plot
            # Since we don't have network coordinates, we'll use a circular layout

            # Create circular layout
            n_stations = len(top_30)
            angles = np.linspace(0, 2*np.pi, n_stations, endpoint=False)
            x_coords = np.cos(angles)
            y_coords = np.sin(angles)

            # Add some randomness to avoid perfect circle
            x_coords += np.random.normal(0, 0.1, n_stations)
            y_coords += np.random.normal(0, 0.1, n_stations)

            top_30_viz = top_30.copy()
            top_30_viz['x'] = x_coords
            top_30_viz['y'] = y_coords

            # Create network diagram
            fig_network = px.scatter(
                top_30_viz,
                x='x',
                y='y',
                size='combined_score',
                color='betweenness_centrality',
                hover_name='stop_name',
                hover_data={
                    'rank': True,
                    'routes_served': True,
                    'betweenness_centrality': ':.3f',
                    'combined_score': ':.3f'
                },
                color_continuous_scale='RdYlGn_r',
                size_max=30,
                labels={
                    'stop_name': 'Station',
                    'combined_score': 'Criticality',
                    'betweenness_centrality': 'Betweenness'
                }
            )

            fig_network.update_layout(
                title="Top 30 Critical Stations by Centrality",
                xaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
                yaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
                height=500,
                margin=dict(l=0, r=0, t=30, b=0),
                showlegend=False
            )

            st.plotly_chart(fig_network, use_container_width=True)
            st.caption("This scatter ranks stations by centrality; it is not a map of physical track connections.")

    else:
        st.warning("No network analysis data found. Run `python -m processing.network_analysis` to generate critical stations data.")

    st.divider()
    st.caption(
        "On-time is based on the final observed realtime prediction being within 5 minutes of schedule. "
        "Unmatched/ambiguous prediction = the realtime record did not have sufficiently strong evidence "
        "for an active static-schedule trip; added service is classified separately."
    )
