"""Train a model and register it, but only if it earns the slot.

This is the file that makes the project MLOps rather than ML. Training is
five lines. Everything else is deciding whether the result is allowed to
replace what is already serving, and recording that decision either way.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

import joblib
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from src.config import settings
from src.db import execute, load_actuals, read_sql
from src.features import build_supervised, feature_columns

HOLDOUT_DAYS = 7  # the last week is never trained on
MIN_HISTORY_HOURS = 24 * 21


def new_version() -> str:
    return datetime.now(timezone.utc).strftime("v%Y%m%d-%H%M")


def train_and_evaluate(series: pd.Series) -> dict:
    horizons = range(1, settings.horizon_hours + 1)
    df = build_supervised(series, horizons)
    if df.empty:
        raise SystemExit("No usable training rows. Check for gaps in actuals.")

    cols = feature_columns(df)

    # Split by time, never randomly. A random split leaks the future into
    # training and produces a score that will not survive contact with
    # production.
    cutoff = df["target_ts"].max() - pd.Timedelta(days=HOLDOUT_DAYS)
    train = df[df["target_ts"] <= cutoff]
    holdout = df[df["target_ts"] > cutoff]

    if train.empty or holdout.empty:
        raise SystemExit("Not enough history to hold out a week.")

    model = make_pipeline(StandardScaler(), Ridge(alpha=1.0))
    model.fit(train[cols], train["y"])

    mae = float(mean_absolute_error(holdout["y"], model.predict(holdout[cols])))
    # The baseline scored on the exact same rows, so the comparison is fair.
    naive_mae = float(mean_absolute_error(holdout["y"], holdout["naive"]))

    return {
        "model": model,
        "mae": mae,
        "naive_mae": naive_mae,
        "train_rows": int(len(train)),
        "holdout_rows": int(len(holdout)),
        "beats_naive": mae < naive_mae,
    }


def current_active_mae() -> float | None:
    df = read_sql("SELECT holdout_mae FROM models WHERE status = 'active' LIMIT 1")
    return None if df.empty else float(df.iloc[0]["holdout_mae"])


def register(version: str, result: dict, status: str, notes: str) -> None:
    if status == "active":
        execute("UPDATE models SET status = 'retired' WHERE status = 'active'", {})
    execute(
        """
        INSERT INTO models (version, train_rows, holdout_mae, status, notes)
        VALUES (:version, :rows, :mae, :status, :notes)
        """,
        {
            "version": version,
            "rows": result["train_rows"],
            "mae": result["mae"],
            "status": status,
            "notes": notes,
        },
    )


def main(force: bool = False) -> int:
    actuals = load_actuals()
    if len(actuals) < MIN_HISTORY_HOURS:
        raise SystemExit(
            f"Only {len(actuals)} hours of history, need {MIN_HISTORY_HOURS}. "
            "Run: python -m src.backfill"
        )

    result = train_and_evaluate(actuals["pm25"])
    version = new_version()
    incumbent = current_active_mae()

    print(f"{version}")
    print(f"  holdout MAE      {result['mae']:.3f}  ({result['holdout_rows']} rows)")
    print(f"  naive baseline   {result['naive_mae']:.3f}")
    print(f"  active model     {incumbent if incumbent is not None else 'none'}")

    # ---- The evaluation gate --------------------------------------------
    # A worse model still runs, still returns 200, and still looks fine on a
    # chart. Nothing about it fails. So something has to be willing to reject
    # it for being merely unremarkable, and that is this block. Rejections
    # are recorded, never deleted: they are the proof the gate does anything.
    if not result["beats_naive"] and not force:
        register(version, result, "rejected", "lost to naive baseline")
        print("REJECTED: does not beat the naive baseline. Active model unchanged.")
        return 1

    if incumbent is not None and result["mae"] >= incumbent and not force:
        register(version, result, "rejected", f"worse than active ({incumbent:.3f})")
        print("REJECTED: worse than the model already serving. Nothing deployed.")
        return 1
    # ----------------------------------------------------------------------

    settings.model_path.mkdir(parents=True, exist_ok=True)
    joblib.dump(result["model"], settings.model_path / f"{version}.pkl")
    joblib.dump(result["model"], settings.model_path / "active.pkl")
    register(
        version,
        result,
        "active",
        f"beats naive by {result['naive_mae'] - result['mae']:.3f}",
    )
    print(f"PROMOTED {version} to active.")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true", help="bypass the gate (don't)")
    raise SystemExit(main(force=p.parse_args().force))
