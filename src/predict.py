"""The hourly job. Ingest, then commit to 24 predictions about the future.

Ordering matters: actuals first, then predict, because the model needs the
freshest reading. The rows this writes have no known answer yet. They sit in
the database waiting for reality, which is the one thing in this project
nobody can fabricate after the fact.
"""

from __future__ import annotations

import time

import joblib
import pandas as pd

from src.config import settings
from src.db import active_model_version, execute, load_actuals
from src.features import feature_columns, latest_features
from src.fetch import ingest

INSERT_FORECAST = """
INSERT INTO forecasts (target_ts, predicted, model_version, horizon_h, latency_ms)
VALUES (:target_ts, :predicted, :version, :horizon_h, :latency_ms)
"""


def make_forecasts() -> pd.DataFrame:
    """Predict every hour from +1 to +horizon in a single batch.

    Horizon is a model feature, so one predict() call covers all 24 steps and
    each row records which horizon it came from. Error by horizon is then a
    free chart: accuracy should decay the further out we look, and if it does
    not, something is wrong with the features.
    """
    model = joblib.load(settings.model_path / "active.pkl")
    version = active_model_version() or "unregistered"

    actuals = load_actuals(limit_hours=settings.lookback_hours * 2)
    if actuals.empty:
        return pd.DataFrame()

    feats = latest_features(actuals["pm25"], range(1, settings.horizon_hours + 1))
    if feats.empty:
        return pd.DataFrame()

    started = time.perf_counter()
    preds = model.predict(feats[feature_columns(feats)])
    latency_ms = int((time.perf_counter() - started) * 1000)

    return pd.DataFrame(
        {
            "target_ts": feats["target_ts"],
            "predicted": preds.clip(min=0.0),  # PM2.5 cannot be negative
            "version": version,
            "horizon_h": feats["horizon"],
            "latency_ms": latency_ms,
        }
    )


def write_forecasts(df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    execute(INSERT_FORECAST, df.to_dict("records"))
    return len(df)


def main() -> None:
    print(f"ingest: {ingest()}")

    forecasts = make_forecasts()
    n = write_forecasts(forecasts)
    if n:
        print(f"wrote {n} forecasts through {forecasts['target_ts'].max()}")
    else:
        print("no forecasts written: not enough history, or no active model")


if __name__ == "__main__":
    main()
