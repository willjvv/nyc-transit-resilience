"""NYC subway analytics dashboard.

The dashboard is intentionally organized around user questions instead of
pipeline internals:

1. Overview   - How is the system doing?
2. Performance - Where and when are delays concentrated?
3. Network    - Which stations are structurally important?
4. Data       - How trustworthy are the measurements?

The underlying metrics are prediction-vs-schedule measurements, not observed
physical arrivals. The UI keeps that distinction visible without requiring the
user to understand the pipeline first.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd
import plotly.express as px
import streamlit as st

DASHBOARD_DIR = Path(__file__).parent
sys.path.insert(0, str(DASHBOARD_DIR))

from explanations import FAQ, THRESHOLDS  # noqa: E402

PROCESSED_DATA_DIR = Path(os.getenv("PROCESSED_DATA_DIR", "data/processed"))
NYC_TZ = ZoneInfo("America/New_York")
ON_TIME_TARGET_PCT = THRESHOLDS["on_time_target"]
QUALITY_WARNING_PCT = THRESHOLDS["quality_warning"]

st.set_page_config(
    page_title="NYC Subway Analytics",
    page_icon="🚇",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ----------------------------- Data helpers -----------------------------


def available_dates() -> list[str]:
    """Return only dates with a completed dashboard metrics artifact.

    Processing creates the date directory before reconciliation/metrics finish,
    so directory existence alone is not enough to make a date selectable.
    """
    if not PROCESSED_DATA_DIR.exists():
        return []
    dates = []
    for path in PROCESSED_DATA_DIR.iterdir():
        if not path.is_dir() or not path.name.startswith("date="):
            continue
        date = path.name.removeprefix("date=")
        if (path / "on_time_by_line.parquet").exists():
            dates.append(date)
    return sorted(dates, reverse=True)


def processing_dates() -> list[str]:
    """Return date partitions even when processing is incomplete."""
    if not PROCESSED_DATA_DIR.exists():
        return []
    return sorted(
        [
            p.name.removeprefix("date=")
            for p in PROCESSED_DATA_DIR.iterdir()
            if p.is_dir() and p.name.startswith("date=")
        ],
        reverse=True,
    )


@st.cache_data(ttl=300)
def load_metric(date: str, filename: str) -> pd.DataFrame:
    path = PROCESSED_DATA_DIR / f"date={date}" / filename
    if not path.exists():
        return pd.DataFrame()
    with duckdb.connect() as con:
        return con.execute("SELECT * FROM read_parquet(?)", [str(path)]).df()


@st.cache_data(ttl=300)
def load_network() -> pd.DataFrame:
    path = PROCESSED_DATA_DIR / "critical_stations.parquet"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def safe_float(value, default=None):
    try:
        result = float(value)
        return default if pd.isna(result) else result
    except (TypeError, ValueError):
        return default


def freshness_label(date: str) -> str:
    try:
        selected = datetime.strptime(date, "%Y-%m-%d").date()
        today = datetime.now(NYC_TZ).date()
        age = (today - selected).days
        if age == 0:
            return "Today"
        if age == 1:
            return "Yesterday"
        return f"{age} days old"
    except ValueError:
        return "Unknown"


def overall_on_time(df: pd.DataFrame):
    if df.empty or "matched_count" not in df or "on_time_count" not in df:
        return None
    matched = pd.to_numeric(df["matched_count"], errors="coerce").sum()
    on_time = pd.to_numeric(df["on_time_count"], errors="coerce").sum()
    return 100.0 * on_time / matched if matched else None


def weighted_avg_delay(df: pd.DataFrame):
    if df.empty or "matched_count" not in df or "avg_prediction_delay_minutes" not in df:
        return None
    weights = pd.to_numeric(df["matched_count"], errors="coerce").fillna(0)
    values = pd.to_numeric(df["avg_prediction_delay_minutes"], errors="coerce")
    total = weights.sum()
    return float((values.fillna(0) * weights).sum() / total) if total else None


def overall_quality(df: pd.DataFrame):
    if df.empty or "total_predictions" not in df:
        return None
    total = pd.to_numeric(df["total_predictions"], errors="coerce").fillna(0).sum()
    issues = (
        pd.to_numeric(df.get("unmatched_count", 0), errors="coerce").fillna(0)
        + pd.to_numeric(df.get("ambiguous_count", 0), errors="coerce").fillna(0)
    ).sum()
    return 100.0 * issues / total if total else None


def performance_label(on_time: float | None) -> str:
    if on_time is None:
        return "No data"
    if on_time >= ON_TIME_TARGET_PCT:
        return "Good"
    if on_time >= THRESHOLDS["on_time_warning"]:
        return "Needs attention"
    return "Poor"


def status_emoji(on_time: float | None) -> str:
    label = performance_label(on_time)
    return {"Good": "🟢", "Needs attention": "🟡", "Poor": "🔴"}.get(label, "⚪")


def route_column(df: pd.DataFrame) -> str:
    if "route_id" in df.columns:
        return "route_id"
    return "line" if "line" in df.columns else "route_id"


def route_name(value) -> str:
    text = str(value)
    return text.replace("SIR", "Staten Island Railway")


def chart_theme(fig, height=420):
    fig.update_layout(
        height=height,
        margin=dict(l=10, r=10, t=45, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        hoverlabel=dict(namelength=-1),
    )
    fig.update_xaxes(showgrid=True, gridcolor="rgba(128,128,128,0.15)")
    fig.update_yaxes(showgrid=False)
    return fig


def show_metric_explanation(label: str, text: str):
    with st.popover(f"About {label}"):
        st.markdown(text)


def line_bar(df: pd.DataFrame):
    if df.empty:
        st.warning("Line performance has not been generated for this service date yet.")
        st.caption("Choose another completed date, or run the parse → reconcile → metrics steps for this date.")
        return
    route_col = route_column(df)
    plot_df = df[[route_col, "on_time_pct"]].copy()
    plot_df[route_col] = plot_df[route_col].map(route_name)
    plot_df["on_time_pct"] = pd.to_numeric(plot_df["on_time_pct"], errors="coerce")
    plot_df = plot_df.dropna(subset=["on_time_pct"]).sort_values("on_time_pct")
    fig = px.bar(
        plot_df,
        x="on_time_pct",
        y=route_col,
        orientation="h",
        text="on_time_pct",
        labels={route_col: "Line", "on_time_pct": "On schedule (%)"},
    )
    fig.update_traces(texttemplate="%{text:.0f}%", textposition="outside")
    fig.add_vline(x=ON_TIME_TARGET_PCT, line_dash="dash", annotation_text="90% target", annotation_position="top")
    fig.update_xaxes(range=[0, 105])
    chart_theme(fig, 430)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def delay_timeline(df: pd.DataFrame, selected_line: str | None = None):
    if df.empty:
        st.info("No hourly delay data is available for this date.")
        return
    route_col = route_column(df)
    plot_df = df.copy()
    if selected_line and selected_line != "All lines":
        plot_df = plot_df[plot_df[route_col].astype(str) == selected_line]
    if plot_df.empty:
        st.info("No delay observations match the selected line.")
        return
    fig = px.line(
        plot_df.sort_values([route_col, "hour_of_day"]),
        x="hour_of_day",
        y="median_prediction_delay_minutes" if "median_prediction_delay_minutes" in plot_df.columns else "avg_prediction_delay_minutes",
        color=route_col if selected_line == "All lines" or selected_line is None else None,
        markers=True,
        labels={
            "hour_of_day": "Hour",
            "median_prediction_delay_minutes": "Median predicted delay (min)",
            "avg_prediction_delay_minutes": "Average predicted delay (min)",
            route_col: "Line",
        },
    )
    fig.add_hline(y=5, line_dash="dash", annotation_text="5-minute on-time threshold", annotation_position="top left")
    fig.update_xaxes(dtick=2, range=[0, 23])
    chart_theme(fig, 460)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def render_about_data():
    st.markdown("### How the numbers are made")
    st.markdown(
        "This dashboard compares **GTFS-realtime arrival predictions** with the active static schedule. "
        "A prediction is not the same thing as an observed physical arrival. Daily performance uses the "
        "terminal prediction observed for each matched trip and stop."
    )
    with st.expander("What counts as on schedule?", expanded=False):
        st.write(
            f"A matched prediction is considered on schedule when its predicted arrival is within "
            f"±5 minutes of the published schedule. The 90% reference target is used as a visual benchmark, "
            "not as an MTA-certified service standard."
        )
    with st.expander("How are realtime trains matched to the schedule?", expanded=False):
        st.write(
            "The reconciliation engine first restricts candidates to the active service date and route/stop, "
            "then uses direction, sequence and time evidence. Matches that are weak or genuinely ambiguous "
            "are retained as quality flags rather than being silently forced into a scheduled trip."
        )
    with st.expander("What does data quality mean?", expanded=False):
        st.write(
            "The quality rate is the share of terminal realtime predictions that were unmatched or ambiguous. "
            "It is a measurement-quality signal: an unmatched prediction can represent added service, a schedule "
            "change, or insufficient matching evidence. It does not mean that a train disappeared."
        )


# ----------------------------- Layout -----------------------------

dates = available_dates()
all_processing_dates = processing_dates()

with st.sidebar:
    st.title("🚇 NYC Subway Analytics")
    st.caption("Realtime prediction vs. schedule")
    page = st.radio("Explore", ["Overview", "Performance", "Network", "Data"], label_visibility="collapsed")
    st.divider()
    if dates:
        selected_date = st.selectbox("Service date", dates, index=0)
        st.caption(f"Data age: **{freshness_label(selected_date)}**")
    else:
        selected_date = None
    st.divider()
    st.caption("Source: MTA GTFS / GTFS-Realtime")

if not dates:
    st.title("NYC Subway Analytics")
    if all_processing_dates:
        st.warning("The pipeline has created data partitions, but none has completed daily line metrics yet.")
        latest = all_processing_dates[0]
        st.info(
            f"Latest processing partition: **{latest}**. "
            "Run reconciliation and metrics for that date, then refresh the dashboard."
        )
        st.code(f"python -m processing.reconcile --date {latest}\npython -m processing.metrics --date {latest}", language="bash")
    else:
        st.warning("No processed data found yet. Run the pipeline before opening the dashboard.")
        st.code("bash scripts/run_local.sh", language="bash")
    st.stop()

on_time_df = load_metric(selected_date, "on_time_by_line.parquet")
delay_df = load_metric(selected_date, "delay_by_hour.parquet")
quality_df = load_metric(selected_date, "prediction_quality_by_line.parquet")
if quality_df.empty:
    # Backward compatibility for metrics generated before the quality-table rename.
    quality_df = load_metric(selected_date, "ghost_rate_by_line.parquet")
network_df = load_network()

system_on_time = overall_on_time(on_time_df)
system_delay = weighted_avg_delay(on_time_df)
system_quality = overall_quality(quality_df)

st.title({
    "Overview": "NYC Subway: How is the system doing?",
    "Performance": "Performance: Where are delays concentrated?",
    "Network": "Network: Which stations matter most?",
    "Data": "Data: How trustworthy are these measurements?",
}[page])
st.caption(f"Service date: {selected_date} · Data age: {freshness_label(selected_date)} · Completed metrics")

# ----------------------------- Overview -----------------------------
if page == "Overview":
    st.markdown("## The big picture")
    if system_on_time is None:
        st.info("There is not enough matched prediction data to summarize this date.")
    else:
        status = performance_label(system_on_time)
        cols = st.columns(3)
        with cols[0]:
            st.metric("On schedule", f"{system_on_time:.1f}%")
            st.caption(f"{status_emoji(system_on_time)} {status} · 90% visual target")
        with cols[1]:
            st.metric("Typical predicted delay", f"{system_delay:.1f} min" if system_delay is not None else "—")
            st.caption("Weighted average across matched trip-stop predictions")
        with cols[2]:
            best = on_time_df.sort_values("on_time_pct", ascending=False).iloc[0] if not on_time_df.empty else None
            st.metric("Most on-schedule line", route_name(best[route_column(on_time_df)]) if best is not None else "—")
            if best is not None:
                st.caption(f"{safe_float(best['on_time_pct']):.1f}% on schedule")

        st.divider()
        st.markdown("## Where are problems showing up?")
        line_bar(on_time_df)
        st.caption("Lines are ranked by the share of matched realtime predictions within ±5 minutes of schedule.")

        worst = on_time_df.sort_values("on_time_pct").head(3) if not on_time_df.empty else pd.DataFrame()
        if not worst.empty:
            st.markdown("### Lines needing the most attention")
            for _, row in worst.iterrows():
                line = route_name(row[route_column(on_time_df)])
                pct = safe_float(row["on_time_pct"], 0)
                st.write(f"**{line}** — {pct:.1f}% on schedule")

        st.divider()
        st.markdown("## What do these numbers mean?")
        render_about_data()

# ----------------------------- Performance -----------------------------
elif page == "Performance":
    st.markdown("Choose a line to inspect timing patterns rather than scanning every series at once.")
    route_col = route_column(delay_df if not delay_df.empty else on_time_df)
    line_values = []
    if route_col in delay_df.columns:
        line_values = sorted(delay_df[route_col].dropna().astype(str).unique().tolist())
    elif route_col in on_time_df.columns:
        line_values = sorted(on_time_df[route_col].dropna().astype(str).unique().tolist())
    selected_line = st.selectbox("Line", ["All lines"] + line_values)

    filtered_on_time = on_time_df.copy()
    if selected_line != "All lines" and route_col in filtered_on_time.columns:
        filtered_on_time = filtered_on_time[filtered_on_time[route_col].astype(str) == selected_line]

    cols = st.columns(3)
    perf_pct = safe_float(filtered_on_time.iloc[0]["on_time_pct"]) if len(filtered_on_time) == 1 else system_on_time
    perf_delay = safe_float(filtered_on_time.iloc[0].get("avg_prediction_delay_minutes")) if len(filtered_on_time) == 1 else system_delay
    perf_quality = None
    if selected_line != "All lines" and not quality_df.empty:
        qcol = route_column(quality_df)
        match = quality_df[quality_df[qcol].astype(str) == selected_line]
        if not match.empty:
            perf_quality = safe_float(match.iloc[0].get("data_quality_issue_pct"))
    else:
        perf_quality = system_quality

    with cols[0]:
        st.metric("On schedule", f"{perf_pct:.1f}%" if perf_pct is not None else "—")
    with cols[1]:
        st.metric("Average predicted delay", f"{perf_delay:.1f} min" if perf_delay is not None else "—")
    with cols[2]:
        st.metric("Unmatched / ambiguous", f"{perf_quality:.1f}%" if perf_quality is not None else "—")

    st.divider()
    st.markdown("## When are delays worst?")
    st.caption("Use the line selector to turn a crowded multi-line chart into a focused view.")
    delay_timeline(delay_df, selected_line)

    st.divider()
    st.markdown("## How each line compares")
    line_bar(on_time_df)

    st.divider()
    with st.expander("Prediction-matching quality by line"):
        if quality_df.empty:
            st.info("No prediction-quality data is available.")
        else:
            qcol = route_column(quality_df)
            qview = quality_df[[qcol, "total_predictions", "unmatched_count", "ambiguous_count", "added_service_count", "data_quality_issue_pct"]].copy()
            qview = qview.rename(columns={
                qcol: "Line",
                "total_predictions": "Predictions",
                "unmatched_count": "Unmatched",
                "ambiguous_count": "Ambiguous",
                "added_service_count": "Added service",
                "data_quality_issue_pct": "Quality issue %",
            })
            st.dataframe(qview, use_container_width=True, hide_index=True)
            st.caption(f"Values above {QUALITY_WARNING_PCT}% deserve investigation; they are not proof of missing trains.")

# ----------------------------- Network -----------------------------
elif page == "Network":
    st.markdown("## Which stations are structurally important?")
    st.caption("The network model uses consecutive scheduled stop pairs and scheduled running time as edge distance.")

    if network_df.empty:
        st.warning("No network analysis data found. Run `python -m processing.network_analysis` first.")
    else:
        top = network_df.head(10).copy()
        cols = st.columns(3)
        for idx, title in enumerate(["Most important station", "Second", "Third"]):
            with cols[idx]:
                row = top.iloc[idx]
                st.metric(title, str(row["stop_name"]))
                st.caption(f"Criticality score {safe_float(row['combined_score'], 0):.2f}")

        st.divider()
        st.markdown("## Station importance map")
        fig = px.scatter_mapbox(
            network_df,
            lat="stop_lat",
            lon="stop_lon",
            size="combined_score",
            color="combined_score",
            hover_name="stop_name",
            hover_data={
                "rank": True,
                "route_count": True,
                "combined_score": ":.2f",
                "stop_lat": False,
                "stop_lon": False,
            },
            labels={"rank": "Network rank", "route_count": "Lines served", "combined_score": "Importance"},
            color_continuous_scale="RdYlGn_r",
            zoom=9.8,
            center={"lat": 40.72, "lon": -73.98},
            size_max=22,
        )
        fig.update_layout(mapbox_style="open-street-map", height=570, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        st.caption("Larger / redder markers indicate higher modeled network importance. This is not a live delay map.")

        with st.expander("Why does a station rank highly?", expanded=False):
            st.markdown(
                "The score combines several structural measures: how often a station sits on shortest paths "
                "(betweenness), how connected it is, how centrally accessible it is, and how strongly it connects "
                "to other well-connected stations. These are network measures—not predictions of passenger impact."
            )

        st.markdown("## Top critical stations")
        view = network_df.head(25).copy()
        view["Routes"] = view["routes_served"].apply(lambda x: ", ".join(x) if isinstance(x, list) else str(x))
        view = view.rename(columns={
            "rank": "Rank",
            "stop_name": "Station",
            "route_count": "Lines served",
            "combined_score": "Importance",
            "betweenness_centrality": "Betweenness",
            "closeness_centrality": "Closeness",
        })
        st.dataframe(
            view[["Rank", "Station", "Routes", "Lines served", "Importance", "Betweenness", "Closeness"]].round(3),
            use_container_width=True,
            hide_index=True,
        )

# ----------------------------- Data -----------------------------
else:
    st.markdown("## Trust, coverage, and methodology")
    cols = st.columns(3)
    with cols[0]:
        st.metric("On-schedule coverage", f"{system_on_time:.1f}%" if system_on_time is not None else "—")
        st.caption("Among matched terminal predictions")
    with cols[1]:
        st.metric("Quality flags", f"{system_quality:.1f}%" if system_quality is not None else "—")
        st.caption("Unmatched or ambiguous terminal predictions")
    with cols[2]:
        matched = int(pd.to_numeric(on_time_df.get("matched_count", pd.Series(dtype=float)), errors="coerce").sum()) if not on_time_df.empty else 0
        st.metric("Matched trip-stops", f"{matched:,}")
        st.caption("Counted once per trip-stop in daily metrics")

    st.divider()
    render_about_data()

    st.divider()
    st.markdown("### Line-level data quality")
    if quality_df.empty:
        st.info("No line-level quality table is available.")
    else:
        qcol = route_column(quality_df)
        qview = quality_df[[qcol, "total_predictions", "unmatched_count", "ambiguous_count", "added_service_count", "data_quality_issue_pct"]].copy()
        qview["quality_status"] = qview["data_quality_issue_pct"].apply(
            lambda x: "High confidence" if safe_float(x, 100) < QUALITY_WARNING_PCT else "Review"
        )
        qview = qview.rename(columns={qcol: "Line", "total_predictions": "Predictions", "unmatched_count": "Unmatched", "ambiguous_count": "Ambiguous", "added_service_count": "Added service", "data_quality_issue_pct": "Issue rate %", "quality_status": "Status"})
        st.dataframe(qview, use_container_width=True, hide_index=True)

    st.divider()
    st.markdown("### Frequently asked questions")
    for item in FAQ:
        with st.expander(item["question"]):
            st.write(item["answer"])

    st.divider()
    st.caption("The dashboard is intentionally explicit about its main limitation: prediction-vs-schedule metrics are not the same as observed-arrival performance.")
