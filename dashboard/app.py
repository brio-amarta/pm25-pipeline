"""Six blocks, one scrolling page, in the order that makes the argument.

Health first, not last. The reader is deciding whether this is a live system
or a screenshot, and a timestamp is the fastest way to settle that.

    streamlit run dashboard/app.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.config import settings  # noqa: E402
from src.db import read_sql  # noqa: E402

st.set_page_config(page_title="PM2.5 Pipeline", layout="wide")


@st.cache_data(ttl=300)
def q(sql: str) -> pd.DataFrame:
    return read_sql(sql)


st.title(f"PM2.5 Forecast Pipeline · {settings.location_name}")
st.caption(
    "A deployed model that logs every prediction before the answer exists, "
    "then grades itself when reality catches up."
)

# ---------------------------------------------------------------- BLOCK 1
# Is this thing alive? Timestamps, not status lights. A green dot proves
# nothing; "14 minutes ago" cannot be faked by a static export.
st.header("1 · Pipeline health")

health = q(
    """
    SELECT
      (SELECT MAX(ts)      FROM actuals)   AS last_actual,
      (SELECT MAX(run_at)  FROM forecasts) AS last_forecast,
      (SELECT MAX(trained_at) FROM models WHERE status='active') AS last_train,
      (SELECT version      FROM models WHERE status='active')    AS version,
      (SELECT COUNT(*)     FROM forecasts) AS total_forecasts,
      (SELECT COUNT(*)     FROM pending_forecasts) AS pending
    """
).iloc[0]


def ago(ts) -> str:
    if pd.isna(ts):
        return "never"
    delta = datetime.now(timezone.utc) - ts
    mins = int(delta.total_seconds() / 60)
    if mins < 60:
        return f"{mins} min ago"
    if mins < 1440:
        return f"{mins // 60} h ago"
    return f"{mins // 1440} d ago"


c = st.columns(6)
c[0].metric("Last data pull", ago(health["last_actual"]))
c[1].metric("Last forecast", ago(health["last_forecast"]))
c[2].metric("Last retrain", ago(health["last_train"]))
c[3].metric("Active model", health["version"] or "none")
c[4].metric("Forecasts logged", f"{int(health['total_forecasts']):,}")
c[5].metric("Awaiting reality", int(health["pending"]))

st.caption(
    f"{int(health['pending'])} predictions are sitting in the database for hours "
    "that have not happened yet. Those rows are the part that cannot be "
    "reconstructed after the fact."
)

# ---------------------------------------------------------------- BLOCK 2
st.header("2 · Next 24 hours")

nxt = q(
    """
    SELECT target_ts, predicted
    FROM forecasts
    WHERE run_at = (SELECT MAX(run_at) FROM forecasts)
    ORDER BY target_ts
    """
)
if nxt.empty:
    st.info("No forecasts yet. Run `python -m src.predict`.")
else:
    current = q("SELECT pm25 FROM actuals ORDER BY ts DESC LIMIT 1")
    if not current.empty:
        st.metric("Current PM2.5", f"{current.iloc[0]['pm25']:.1f} µg/m³")
    st.altair_chart(
        alt.Chart(nxt)
        .mark_line(point=True)
        .encode(x="target_ts:T", y=alt.Y("predicted:Q", title="µg/m³")),
        use_container_width=True,
    )

# ---------------------------------------------------------------- BLOCK 3
# The money chart. Two lines that were written at different times.
st.header("3 · Forecast vs actual, last 7 days")

vs = q(
    """
    SELECT target_ts, predicted, actual
    FROM scored_forecasts
    WHERE target_ts > NOW() - INTERVAL '7 days' AND horizon_h = 24
    ORDER BY target_ts
    """
)
if vs.empty:
    st.info("Nothing scored yet. Forecasts need 24h before reality catches up.")
else:
    long = vs.melt("target_ts", ["predicted", "actual"], "series", "value")
    st.altair_chart(
        alt.Chart(long)
        .mark_line()
        .encode(x="target_ts:T", y=alt.Y("value:Q", title="µg/m³"), color="series:N"),
        use_container_width=True,
    )

# ---------------------------------------------------------------- BLOCK 4
st.header("4 · Error over time")

err = q(
    """
    SELECT date_trunc('day', target_ts) AS day,
           AVG(abs_error) AS mae,
           model_version
    FROM scored_forecasts
    WHERE target_ts > NOW() - INTERVAL '30 days'
    GROUP BY 1, model_version
    ORDER BY 1
    """
)
if err.empty:
    st.info("Not enough scored history yet.")
else:
    st.altair_chart(
        alt.Chart(err)
        .mark_line(point=True)
        .encode(
            x="day:T",
            y=alt.Y("mae:Q", title="MAE µg/m³"),
            color=alt.Color("model_version:N", title="model"),
        ),
        use_container_width=True,
    )
    st.caption(
        "Colour changes where a new model took over. A rise that only shows up "
        "in this line is model decay; a rise the benchmarks share is a hard week."
    )

# ---------------------------------------------------------------- BLOCK 5
# Not a vanity chart. Without a reference that lived through the same week,
# a jump in our error is ambiguous.
st.header("5 · Compared to what?")

board = q(
    """
    SELECT 'this model' AS source, AVG(abs_error) AS mae, COUNT(*) AS n
    FROM scored_forecasts
    WHERE target_ts > NOW() - INTERVAL '7 days'
    UNION ALL
    SELECT b.source, AVG(ABS(b.predicted - a.pm25)), COUNT(*)
    FROM benchmark b JOIN actuals a ON a.ts = b.target_ts
    WHERE b.target_ts > NOW() - INTERVAL '7 days'
    GROUP BY b.source
    """
)
if board.empty or board["mae"].isna().all():
    st.info("Benchmarks need a week of overlap before they mean anything.")
else:
    st.dataframe(board.dropna(subset=["mae"]).round(2), use_container_width=True)

# ---------------------------------------------------------------- BLOCK 6
# Rejected rows are the point. They show the gate turned something down
# while nobody was watching.
st.header("6 · Model history")

hist = q(
    "SELECT version, trained_at, train_rows, holdout_mae, status, notes "
    "FROM models ORDER BY trained_at DESC"
)
if hist.empty:
    st.info("No models registered yet.")
else:
    st.dataframe(hist, use_container_width=True)
    rejected = int((hist["status"] == "rejected").sum())
    if rejected:
        st.caption(
            f"{rejected} version(s) were built and refused promotion for being "
            "worse than what was already serving. Nobody intervened."
        )
