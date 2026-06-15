import pandas as pd
import numpy as np
import streamlit as st
import altair as alt

# Google Sheets -> Excel export URL
SHEET_ID = "1At6UmzaaCc9VYC1lLzs39wJQOcIDwHcyGFsHMp4JPGw"
EXCEL_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=xlsx"


@st.cache_data(ttl="15m")
def load_data_from_gsheet() -> pd.DataFrame:
    xls = pd.ExcelFile(EXCEL_URL)

    dfs = []
    for sheet in xls.sheet_names:
        df = pd.read_excel(xls, sheet_name=sheet)
        df["Season"] = sheet
        dfs.append(df)

    df = pd.concat(dfs, ignore_index=True)

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")

    # 1 if Player_SGP won, 0 if opponent won
    df["Result_win"] = (df["Winner"] == "Player").astype("int")

    # Clean numeric metric columns if present
    for col in [
        "Average_Rally_Duration",
        "Average_Rest_Duration",
        "Rally_ShortDistribution_pct",
        "Rally_MidDistribution_pct",
        "Rally_LongDistribution_pct",
        "Player_Serve_Win_pct",
        "Player_Pressure_Pts_Won_pct",
        "Total_player_Pts_won_pct",
        "Opponent_Serve_Loss_pct",  # points player wins on opponent serve
    ]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


df = load_data_from_gsheet()

st.title("HPSI Badminton Performance Explorer")

# --- Sidebar controls ---
st.sidebar.header("Filters")

player = st.sidebar.selectbox(
    "Select SGP player",
    sorted(df["Player_SGP"].dropna().unique())
)

player_df = df[df["Player_SGP"] == player].copy()
player_df = player_df.sort_values("Date")

if player_df.empty:
    st.warning("No matches found for this player.")
    st.stop()

filter_mode = st.sidebar.radio(
    "Filter mode",
    ["Last X months", "Last N competitions", "Specific opponent"]
)

filtered = player_df.copy()
latest_date = player_df["Date"].max()

if filter_mode == "Last X months":
    months = st.sidebar.selectbox("Months window", [3, 6, 9, 12], index=0)
    cutoff = latest_date - pd.DateOffset(months=months)
    filtered = player_df[player_df["Date"] >= cutoff]

elif filter_mode == "Last N competitions":
    # competitions ordered from most recent to oldest
    comps_ordered = (
        player_df.sort_values("Date", ascending=False)["Competition"]
        .dropna()
        .unique()
    )
    max_comp = int(len(comps_ordered))          # total competitions for this player
    default_n = min(10, max_comp)               # nice default

    n_comp = st.sidebar.slider(
        "Number of competitions",
        min_value=1,
        max_value=max_comp,                     # scale matches actual number
        value=default_n,
    )

    selected_comps = comps_ordered[:n_comp]
    filtered = player_df[player_df["Competition"].isin(selected_comps)]

elif filter_mode == "Specific opponent":
    opps = (
        player_df["Opponent"]
        .dropna()
        .sort_values()
        .unique()
    )
    opponent = st.sidebar.selectbox("Select opponent", opps)
    filtered = player_df[player_df["Opponent"] == opponent]

# --- Main summary ---
st.subheader(f"Match summary for {player}")

if filtered.empty:
    st.warning("No matches found with the current filters.")
    st.stop()

n_matches = len(filtered)
win_rate = filtered["Result_win"].mean() * 100

col1, col2, col3 = st.columns(3)
col1.metric("Matches", n_matches)
col2.metric("Win rate (%)", f"{win_rate:.1f}")
col3.metric(
    "Date range",
    f"{filtered['Date'].min().date()} → {filtered['Date'].max().date()}"
)

# --- Key averages ---
metric_cols = [
    "Average_Rally_Duration",
    "Average_Rest_Duration",
    "Rally_ShortDistribution_pct",
    "Rally_MidDistribution_pct",
    "Rally_LongDistribution_pct",
    "Total_player_Pts_won_pct",
    "Player_Serve_Win_pct",
    "Player_Pressure_Pts_Won_pct",
    "Opponent_Serve_Loss_pct",
]
avail_metrics = [c for c in metric_cols if c in filtered.columns]

if avail_metrics:
    st.subheader("Average match statistics (filtered set)")
    avg_stats = (
        filtered[avail_metrics]
        .mean()
        .to_frame("Average")
        .reset_index()
        .rename(columns={"index": "Metric"})
    )
    st.dataframe(avg_stats, use_container_width=True)
else:
    st.info("No numeric performance metrics available for this selection.")

# Helper: metric + simple trendline using numpy
def plot_metric_with_trend(df_subset: pd.DataFrame, metric_col: str, y_label: str):
    if metric_col not in df_subset.columns:
        st.info(f"{metric_col} not found in data.")
        return

    d = df_subset[["Date", metric_col]].dropna().sort_values("Date").copy()
    if d.empty:
        st.info(f"No data available for {metric_col} under current filters.")
        return

    x = np.arange(len(d), dtype=float)
    y = d[metric_col].values.astype(float)

    if len(y) >= 2 and not np.allclose(y, y[0]):
        coef = np.polyfit(x, y, 1)
        d["Trend"] = coef[0] * x + coef[1]
    else:
        d["Trend"] = y

    d = d.set_index("Date")
    st.line_chart(d[[metric_col, "Trend"]])
    st.caption("Solid line = metric, second line = simple linear trend.")

# --- Automatic time-series charts for rally distributions ---
filtered = filtered.sort_values("Date")

st.subheader("Rally distribution time-series")

st.markdown("**Short rally distribution (%) over time**")
plot_metric_with_trend(
    filtered,
    "Rally_ShortDistribution_pct",
    y_label="Short rally %",
)

st.markdown("**Medium rally distribution (%) over time**")
plot_metric_with_trend(
    filtered,
    "Rally_MidDistribution_pct",
    y_label="Medium rally %",
)

st.markdown("**Long rally distribution (%) over time**")
plot_metric_with_trend(
    filtered,
    "Rally_LongDistribution_pct",
    y_label="Long rally %",
)

# --- Combined serve chart: grouped bars + trendlines using Altair ---
st.subheader("Serve performance over time")

serve_cols = ["Player_Serve_Win_pct", "Opponent_Serve_Loss_pct"]
if all(c in filtered.columns for c in serve_cols):
    serve_df = filtered[["Date", "Competition", "Opponent"] + serve_cols].dropna().copy()
    if not serve_df.empty:
        # Melt into long format
        melted = serve_df.melt(
            id_vars=["Date", "Competition", "Opponent"],
            value_vars=serve_cols,
            var_name="Metric",
            value_name="Percentage",
        )

        metric_labels = {
            "Player_Serve_Win_pct": "Player serve win %",
            "Opponent_Serve_Loss_pct": "Points won on opponent's serve %",
        }
        melted["Metric_label"] = melted["Metric"].map(metric_labels)

        # Order index for regression (trendlines)
        melted = melted.sort_values("Date")
        melted["order"] = melted.groupby("Metric_label").cumcount().astype(float)

        base = alt.Chart(melted).encode(
            x=alt.X(
                "Date:T",
                title="Month",
                axis=alt.Axis(format="%b", labelAngle=0),  # show only month name
            ),
            y=alt.Y("Percentage:Q", title="Percentage"),
            color=alt.Color("Metric_label:N", title="Metric"),
            tooltip=[
                alt.Tooltip("Date:T"),
                alt.Tooltip("Competition:N"),
                alt.Tooltip("Opponent:N"),
                alt.Tooltip("Metric_label:N", title="Metric"),
                alt.Tooltip("Percentage:Q", format=".1f"),
            ],
        )

        # Side‑by‑side bars (grouped by date, offset by metric)
        bars = base.mark_bar(opacity=0.7, size=10).encode(
            xOffset="Metric_label:N"
        )

        # Separate trendline for each metric using the order index
        lines = alt.Chart(melted).transform_regression(
            "order", "Percentage", groupby=["Metric_label"], method="linear"
        ).mark_line().encode(
            x=alt.X(
                "Date:T",
                axis=alt.Axis(format="%b", labelAngle=0),
            ),
            y="Percentage:Q",
            color="Metric_label:N",
        )

        serve_chart = (bars + lines).properties(
            height=320,
            title="Player serve win % vs points won on opponent's serve %",
        )

        st.altair_chart(serve_chart, use_container_width=True)
    else:
        st.info("No serve data available under current filters.")
else:
    st.info("Serve columns not found in data.")

# --- Optional: interactive time-series for any metric ---
st.subheader("Custom trend across matches")

filtered["Match_label"] = (
    filtered["Date"].dt.strftime("%Y-%m-%d") + " | " +
    filtered["Competition"].astype(str) + " vs " +
    filtered["Opponent"].astype(str)
)

ts_metric_options = [m for m in avail_metrics if filtered[m].notna().any()]
ts_metric = st.selectbox(
    "Metric to plot vs matches",
    ts_metric_options,
)

if ts_metric:
    ts_df = filtered.set_index("Match_label")[[ts_metric]]
    st.line_chart(ts_df)

# --- Rally length distribution (aggregated) ---
dist_cols = [
    "Rally_ShortDistribution_pct",
    "Rally_MidDistribution_pct",
    "Rally_LongDistribution_pct",
]

if all(col in filtered.columns for col in dist_cols):
    st.subheader("Rally length distribution (averaged over filtered matches)")
    dist_means = filtered[dist_cols].mean()
    dist_df = pd.DataFrame(
        {
            "Rally_length": ["Short", "Mid", "Long"],
            "Percentage": [
                dist_means["Rally_ShortDistribution_pct"],
                dist_means["Rally_MidDistribution_pct"],
                dist_means["Rally_LongDistribution_pct"],
            ],
        }
    ).set_index("Rally_length")
    st.bar_chart(dist_df)

# --- Opponent-specific profile (when relevant) ---
if filter_mode == "Specific opponent":
    st.subheader(f"Opponent profile: {player} vs {opponent}")

    vs_opp = player_df[player_df["Opponent"] == opponent]
    vs_others = player_df[player_df["Opponent"] != opponent]

    comp_metrics = [m for m in avail_metrics if player_df[m].notna().any()]

    def agg(df_):
        return df_[comp_metrics].mean().rename("Value").to_frame()

    opp_stats = agg(vs_opp).rename_axis("Metric").reset_index()
    opp_stats["Group"] = f"vs {opponent}"

    other_stats = agg(vs_others).rename_axis("Metric").reset_index()
    other_stats["Group"] = "vs all others"

    comp_df = pd.concat([opp_stats, other_stats], ignore_index=True)

    st.write("Average metrics vs selected opponent vs all other opponents.")
    st.dataframe(
        comp_df.pivot(index="Metric", columns="Group", values="Value"),
        use_container_width=True,
    )

    metric_for_bar = st.selectbox(
        "Metric to compare vs opponent vs all others",
        comp_metrics,
    )

    comp_sub = (
        comp_df[comp_df["Metric"] == metric_for_bar]
        .set_index("Group")[["Value"]]
    )
    st.bar_chart(comp_sub)
