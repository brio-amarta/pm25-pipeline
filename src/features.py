"""Turn a single time series into a supervised learning problem.

Deliberately boring. The model is a prop; the pipeline around it is the
project. Everything here is lags and calendar features, nothing clever.

Multi-horizon strategy: DIRECT, with the horizon as a feature. One model
predicts every step from +1h to +24h, and `horizon` is just another column.
The alternative, one model per horizon, means 24 artifacts to version and
promote, which is 24 times the registry work for no gain at this scale.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Which past hours the model sees. 1-6 for recent momentum, 24 for
# yesterday's same hour, 168 for last week's same hour.
LAGS = [1, 2, 3, 4, 5, 6, 12, 24, 48, 168]
ROLLING_WINDOWS = [3, 24]

TARGET = "y"
HORIZON_COL = "horizon"


def _base_features(series: pd.Series) -> pd.DataFrame:
    """Everything knowable at time t, using only data up to and including t.

    No calendar features here. They belong to the timestamp being predicted,
    not the one being predicted from: a model told it is 09:00 now, with no
    idea whether it is forecasting 10:00 or 09:00 tomorrow, cannot express a
    daily cycle at all and will lose to a naive baseline.
    """
    df = pd.DataFrame({"pm25": series.astype(float)})
    df = df.asfreq("h")  # make gaps explicit rather than silently shifting lags

    for lag in LAGS:
        df[f"lag_{lag}"] = df["pm25"].shift(lag)

    for w in ROLLING_WINDOWS:
        df[f"roll_mean_{w}"] = df["pm25"].rolling(w).mean()
        df[f"roll_std_{w}"] = df["pm25"].rolling(w).std()

    return df.drop(columns=["pm25"])


def _calendar(target_ts: pd.DatetimeIndex) -> dict[str, np.ndarray]:
    """Cyclical encodings of the hour being forecast."""
    return {
        "hour_sin": np.sin(2 * np.pi * target_ts.hour / 24),
        "hour_cos": np.cos(2 * np.pi * target_ts.hour / 24),
        "dow_sin": np.sin(2 * np.pi * target_ts.dayofweek / 7),
        "dow_cos": np.cos(2 * np.pi * target_ts.dayofweek / 7),
    }


def build_supervised(series: pd.Series, horizons: range | list[int]) -> pd.DataFrame:
    """Training frame. One row per (timestamp, horizon) pair.

    `y` is the observed value `horizon` hours after the row's timestamp, so
    every row is a question the model could have been asked in the past and
    an answer we now know.

    Also carries `naive` (the value at t-168+h, i.e. same hour last week)
    so the baseline is scored on exactly the same rows as the model.
    """
    base = _base_features(series)
    values = series.astype(float).asfreq("h")

    frames = []
    for h in horizons:
        f = base.copy()
        f[HORIZON_COL] = h
        target_ts = f.index + pd.Timedelta(hours=h)
        for name, vals in _calendar(target_ts).items():
            f[name] = vals
        f[TARGET] = values.shift(-h)
        f["naive"] = values.shift(-h + 168)  # same clock hour, one week earlier
        f["target_ts"] = target_ts
        frames.append(f)

    out = pd.concat(frames)
    return out.dropna().sort_values("target_ts")


def latest_features(series: pd.Series, horizons: range | list[int]) -> pd.DataFrame:
    """One row per horizon, predicting forward from the end of the series.

    These rows have no known target, which is the entire point: we commit to
    a number before the answer exists.
    """
    base = _base_features(series)
    base = base.dropna()
    if base.empty:
        return pd.DataFrame()

    last = base.tail(1)
    last_ts = last.index[-1]

    rows = []
    for h in horizons:
        r = last.copy()
        r[HORIZON_COL] = h
        target_ts = pd.DatetimeIndex([last_ts + pd.Timedelta(hours=h)])
        for name, vals in _calendar(target_ts).items():
            r[name] = vals
        r["target_ts"] = target_ts[0]
        rows.append(r)

    return pd.concat(rows).reset_index(drop=True)


def feature_columns(df: pd.DataFrame) -> list[str]:
    """Model inputs only. Excludes the target and bookkeeping columns."""
    drop = {TARGET, "naive", "target_ts"}
    return [c for c in df.columns if c not in drop]


def naive_baseline(series: pd.Series, horizon: int = 24) -> float:
    """Same clock hour last week. Five lines, and hard to beat.

    Every chart shows the model against this. A model that cannot beat it is
    not earning its deployment.
    """
    offset = 168 - horizon
    if len(series) > offset >= 0:
        return float(series.iloc[-1 - offset])
    return float(series.iloc[-1])
