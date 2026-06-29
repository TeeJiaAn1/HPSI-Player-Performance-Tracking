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
        "Opponent_Serve_Loss_pct",
        "Player_UFE",
        "Player_FE",
        "Player_Pressured_UFE",
        "Player_%Point_Gained",
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
    comps_ordered = (
        player_df.sort_values("Date", ascending=False)["Competition"]
        .dropna()
        .unique()
    )
    max_comp = int(len(comps_ordered))
    default_n = min(10, max_comp)

    n_comp = st.sidebar.slider(
        "Number of competitions",
        min_value=1,
        max_value=max_comp,
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

filtered = filtered.sort_values("Date").copy()

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


# --- Rally distribution as 3 separate bar charts ---
st.subheader("Rally distribution over time")


def plot_single_rally_bar(df_subset: pd.DataFrame, metric_col: str, chart_title: str):
    if metric_col not in df_subset.columns:
        st.info(f"{metric_col} not found in data.")
        return

    chart_df = df_subset[
        ["Date", "Competition", "Opponent", "Result_win", metric_col]
    ].dropna().copy()

    if chart_df.empty:
        st.info(f"No data available for {chart_title} under current filters.")
        return

    chart_df = chart_df.sort_values("Date").reset_index(drop=True)
    chart_df["Match_index"] = np.arange(len(chart_df), dtype=float)

    chart_df["Match_result"] = np.where(
        chart_df["Result_win"] == 1,
        "Match won",
        "Match lost"
    )

    chart_df["Match_label_full"] = (
        chart_df["Opponent"].astype(str) + " | " +
        chart_df["Competition"].astype(str)
    )

    chart_df["Match_label_axis"] = (
        chart_df["Opponent"].astype(str) + " | " +
        chart_df["Competition"].astype(str).str.slice(0, 28)
    )

    match_order = chart_df["Match_label_axis"].tolist()

    # --- compute simple linear trend ---
    x = chart_df["Match_index"].values.astype(float)
    y = chart_df[metric_col].values.astype(float)

    if len(y) >= 2 and not np.allclose(y, y[0]):
        coef = np.polyfit(x, y, 1)
        chart_df["Trend"] = coef[0] * x + coef[1]
    else:
        chart_df["Trend"] = y

    bars = alt.Chart(chart_df).mark_bar(size=22).encode(
        x=alt.X(
            "Match_label_axis:N",
            title="Opponent | Competition",
            sort=match_order,
            axis=alt.Axis(
                labelAngle=-45,
                labelLimit=500,
                labelOverlap=False
            ),
        ),
        y=alt.Y(
            f"{metric_col}:Q",
            title="Percentage (%)"
        ),
        color=alt.Color(
            "Match_result:N",
            scale=alt.Scale(
                domain=["Match won", "Match lost"],
                range=["#1f77b4", "#d62728"]
            ),
            legend=None
        ),
        tooltip=[
            alt.Tooltip("Date:T", title="Date"),
            alt.Tooltip("Competition:N", title="Competition"),
            alt.Tooltip("Opponent:N", title="Opponent"),
            alt.Tooltip("Match_result:N", title="Match result"),
            alt.Tooltip(f"{metric_col}:Q", title=chart_title, format=".1f"),
        ],
    )

    line = alt.Chart(chart_df).mark_line(
        color="#222222",
        strokeWidth=2.5,
        point=False
    ).encode(
        x=alt.X(
            "Match_label_axis:N",
            sort=match_order
        ),
        y=alt.Y("Trend:Q"),
        tooltip=[
            alt.Tooltip("Match_label_full:N", title="Match"),
            alt.Tooltip("Trend:Q", title="Trend", format=".1f"),
        ],
    )

    chart = (bars + line).properties(
        height=320,
        title=chart_title
    )

    st.altair_chart(chart, use_container_width=True)
    st.caption("Blue = match won, red = match lost, black line = trend.")


plot_single_rally_bar(
    filtered,
    "Rally_ShortDistribution_pct",
    "Short rally distribution (%)"
)

plot_single_rally_bar(
    filtered,
    "Rally_MidDistribution_pct",
    "Mid rally distribution (%)"
)

plot_single_rally_bar(
    filtered,
    "Rally_LongDistribution_pct",
    "Long rally distribution (%)"
)
# --- Work–rest time-series ---
st.subheader("Work–rest time-series")

st.markdown("**Average rally duration (s) over time**")
plot_metric_with_trend(
    filtered,
    "Average_Rally_Duration",
    y_label="Average rally duration (s)",
)

st.markdown("**Average rest duration (s) over time**")
plot_metric_with_trend(
    filtered,
    "Average_Rest_Duration",
    y_label="Average rest duration (s)",
)

# --- Combined serve chart: grouped bars per match, clearer styling ---
st.subheader("Serve performance over time")

serve_cols = ["Player_Serve_Win_pct", "Opponent_Serve_Loss_pct"]

if all(c in filtered.columns for c in serve_cols):
    serve_df = filtered[
        ["Date", "Competition", "Opponent", "Result_win"] + serve_cols
    ].dropna().copy()

    if not serve_df.empty:
        serve_df = serve_df.sort_values("Date").reset_index(drop=True)
        serve_df["Match_index"] = np.arange(len(serve_df), dtype=float)

        serve_df["Match_result"] = np.where(
            serve_df["Result_win"] == 1,
            "Match won",
            "Match lost"
        )

        serve_df["Match_label_full"] = (
            serve_df["Opponent"].astype(str) + " | " +
            serve_df["Competition"].astype(str)
        )

        serve_df["Match_label_axis"] = (
            serve_df["Opponent"].astype(str) + " | " +
            serve_df["Competition"].astype(str).str.slice(0, 28)
        )

        match_order = serve_df["Match_label_axis"].tolist()

        melted = serve_df.melt(
            id_vars=[
                "Date",
                "Competition",
                "Opponent",
                "Result_win",
                "Match_result",
                "Match_index",
                "Match_label_full",
                "Match_label_axis",
            ],
            value_vars=serve_cols,
            var_name="Metric",
            value_name="Percentage",
        )

        metric_labels = {
            "Player_Serve_Win_pct": "Player serve win %",
            "Opponent_Serve_Loss_pct": "Points won on opponent's serve %",
        }
        melted["Metric_label"] = melted["Metric"].map(metric_labels)

        # Four bar shades, but no legend shown for them
        melted["Bar_color_group"] = np.select(
            [
                (melted["Match_result"] == "Match won") & (melted["Metric_label"] == "Player serve win %"),
                (melted["Match_result"] == "Match won") & (melted["Metric_label"] == "Points won on opponent's serve %"),
                (melted["Match_result"] == "Match lost") & (melted["Metric_label"] == "Player serve win %"),
                (melted["Match_result"] == "Match lost") & (melted["Metric_label"] == "Points won on opponent's serve %"),
            ],
            [
                "won_match_serve",
                "won_match_return",
                "lost_match_serve",
                "lost_match_return",
            ],
            default="other"
        )

        bars = alt.Chart(melted).mark_bar(size=16).encode(
            x=alt.X(
                "Match_label_axis:N",
                title="Opponent | Competition",
                sort=match_order,
                axis=alt.Axis(
                    labelAngle=-45,
                    labelLimit=500,
                    labelOverlap=False
                ),
            ),
            xOffset=alt.XOffset("Metric_label:N"),
            y=alt.Y("Percentage:Q", title="Percentage (%)"),
            color=alt.Color(
                "Bar_color_group:N",
                scale=alt.Scale(
                    domain=[
                        "won_match_serve",
                        "won_match_return",
                        "lost_match_serve",
                        "lost_match_return",
                    ],
                    range=[
                        "#1f77b4",  # dark blue
                        "#9ecae1",  # light blue
                        "#d62728",  # dark red
                        "#f4a6a6",  # light red
                    ],
                ),
                legend=None
            ),
            tooltip=[
                alt.Tooltip("Date:T", title="Date"),
                alt.Tooltip("Competition:N", title="Competition"),
                alt.Tooltip("Opponent:N", title="Opponent"),
                alt.Tooltip("Match_result:N", title="Match result"),
                alt.Tooltip("Metric_label:N", title="Metric"),
                alt.Tooltip("Percentage:Q", title="Percentage", format=".1f"),
            ],
        )

        trend_rows = []
        for metric_name, sub in melted.groupby("Metric_label"):
            sub = sub.sort_values("Match_index").copy()
            x = sub["Match_index"].values.astype(float)
            y = sub["Percentage"].values.astype(float)

            if len(y) >= 2 and not np.allclose(y, y[0]):
                coef = np.polyfit(x, y, 1)
                sub["Trend"] = coef[0] * x + coef[1]
            else:
                sub["Trend"] = y

            trend_rows.append(
                sub[["Match_label_axis", "Metric_label", "Trend"]]
            )

        trend_df = pd.concat(trend_rows, ignore_index=True)

        lines = alt.Chart(trend_df).mark_line(strokeWidth=2.5).encode(
            x=alt.X("Match_label_axis:N", sort=match_order),
            xOffset=alt.XOffset("Metric_label:N"),
            y=alt.Y("Trend:Q"),
            detail="Metric_label:N",
            color=alt.Color(
                "Metric_label:N",
                title="Trendline",
                scale=alt.Scale(
                    domain=[
                        "Player serve win %",
                        "Points won on opponent's serve %",
                    ],
                    range=["#08306b", "#fb8c00"]
                ),
                legend=alt.Legend(orient="right")
            ),
            tooltip=[
                alt.Tooltip("Match_label_axis:N", title="Match"),
                alt.Tooltip("Metric_label:N", title="Trendline"),
                alt.Tooltip("Trend:Q", title="Trend", format=".1f"),
            ],
        )

        serve_chart = (bars + lines).properties(
            height=450,
            title="Player serve win % vs points won on opponent's serve %"
        )

        st.altair_chart(serve_chart, use_container_width=True)

        st.caption(
            "Bar colours: dark blue = player serve win % in matches won, "
            "light blue = points won on opponent's serve % in matches won, "
            "dark red = player serve win % in matches lost, "
            "light red = points won on opponent's serve % in matches lost."
        )
    else:
        st.info("No serve data available under current filters.")
else:
    st.info("Serve columns not found in data.")

# --- Detailed error and point-gain profiles ---
st.subheader("Error and point-gain profiles over time")

st.markdown("**Player unforced errors per match**")
plot_metric_with_trend(
    filtered,
    "Player_UFE",
    y_label="Unforced errors (count)",
)

st.markdown("**Player forced errors per match**")
plot_metric_with_trend(
    filtered,
    "Player_FE",
    y_label="Forced errors (count)",
)

st.markdown("**Player pressured unforced errors per match**")
plot_metric_with_trend(
    filtered,
    "Player_Pressured_UFE",
    y_label="Pressured unforced errors (count)",
)

st.markdown("**Player % point gained per match**")
plot_metric_with_trend(
    filtered,
    "Player_%Point_Gained",
    y_label="% points gained",
)

# --- Optional: interactive time-series for any metric ---
st.subheader("Custom trend across matches")

filtered["Match_label"] = (
    filtered["Date"].dt.strftime("%Y-%m-%d") + " | " +
    filtered["Competition"].astype(str) + " vs " +
    filtered["Opponent"].astype(str)
)

ts_metric_options = [m for m in avail_metrics if filtered[m].notna().any()]

if ts_metric_options:
    ts_metric = st.selectbox(
        "Metric to plot vs matches",
        ts_metric_options,
    )

    ts_df = filtered.set_index("Match_label")[[ts_metric]]
    st.line_chart(ts_df)
else:
    st.info("No plottable metrics available for this filtered selection.")

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
