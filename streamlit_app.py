import pandas as pd
import streamlit as st

# Google Sheets -> Excel export URL
SHEET_ID = "1At6UmzaaCc9VYC1lLzs39wJQOcIDwHcyGFsHMp4JPGw"
EXCEL_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=xlsx"

@st.cache_data
def load_data_from_gsheet() -> pd.DataFrame:
    # Read the whole Google Sheets workbook as an Excel file over HTTP
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
    n_comp = st.sidebar.slider("Number of competitions", 1, 10, 3)
    comps_ordered = (
        player_df.sort_values("Date", ascending=False)["Competition"]
        .dropna()
        .unique()
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

# --- Time-series plots for selected metrics ---
st.subheader("Trend across matches")

filtered = filtered.sort_values("Date")
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
