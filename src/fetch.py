"""Pull PM2.5 from Open-Meteo and write it to Postgres.

Two things land here every hour:
  1. actuals   - what the air was really like
  2. benchmark - what CAMS said it would be, so we have a reference that
                 experiences the same weeks we do

Open-Meteo returns parallel arrays: hourly.time[] and hourly.<variable>[].
No API key. Free for non-commercial use.
"""

from __future__ import annotations

import httpx
import pandas as pd

from src.config import settings
from src.db import execute


def _get(params: dict) -> dict:
    with httpx.Client(timeout=30) as client:
        r = client.get(settings.air_quality_url, params=params)
        r.raise_for_status()
        return r.json()


def _to_frame(payload: dict, variable: str) -> pd.DataFrame:
    hourly = payload["hourly"]
    df = pd.DataFrame({"ts": hourly["time"], variable: hourly[variable]})
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df.dropna(subset=[variable])


def fetch_history(past_days: int = 92) -> pd.DataFrame:
    """Backfill. Run once on day one to seed the actuals table.

    past_days is capped by the API; for a longer history use the archive
    endpoint instead. Three months is plenty to train a lag model.
    """
    payload = _get(
        {
            "latitude": settings.latitude,
            "longitude": settings.longitude,
            "hourly": "pm2_5",
            "past_days": past_days,
            "forecast_days": 0,
            "timezone": "UTC",
        }
    )
    return _to_frame(payload, "pm2_5").rename(columns={"pm2_5": "pm25"})


def fetch_recent_actuals(past_days: int = 2) -> pd.DataFrame:
    """The hourly job's first step. Small window, upserted.

    forecast_days=1 is deliberate. In this API the current day sits in the
    forecast window, so forecast_days=0 stops at the end of yesterday and
    leaves actuals up to a day stale -- which makes most of a 24h horizon a
    claim about hours that already happened. We widen the window, then clip:
    past the current hour these values are CAMS model output, and actuals
    must stay observations or there is nothing honest to score against.
    """
    payload = _get(
        {
            "latitude": settings.latitude,
            "longitude": settings.longitude,
            "hourly": "pm2_5",
            "past_days": past_days,
            "forecast_days": 1,
            "timezone": "UTC",
        }
    )
    df = _to_frame(payload, "pm2_5").rename(columns={"pm2_5": "pm25"})
    return df[df["ts"] <= pd.Timestamp.now(tz="UTC").floor("h")]


def fetch_cams_forecast(forecast_days: int = 2) -> pd.DataFrame:
    """CAMS is ECMWF's operational air quality forecast.

    This is the benchmark line. Without it a rise in our error is ambiguous:
    we cannot tell a decaying model from a genuinely unpredictable week.
    """
    payload = _get(
        {
            "latitude": settings.latitude,
            "longitude": settings.longitude,
            "hourly": "pm2_5",
            "forecast_days": forecast_days,
            "past_days": 0,
            "domains": "cams_global",
            "timezone": "UTC",
        }
    )
    df = _to_frame(payload, "pm2_5").rename(
        columns={"pm2_5": "predicted", "ts": "target_ts"}
    )
    df["source"] = "cams"
    # Hours that have already elapsed come back as analysis, not forecast --
    # the same numbers actuals gets -- so scoring them is a guaranteed zero
    # and the benchmark ends up measuring itself. Keep only real predictions.
    return df[df["target_ts"] > pd.Timestamp.now(tz="UTC").floor("h")]


UPSERT_ACTUALS = """
INSERT INTO actuals (ts, pm25)
VALUES (:ts, :pm25)
ON CONFLICT (ts) DO UPDATE SET pm25 = EXCLUDED.pm25
"""

INSERT_BENCHMARK = """
INSERT INTO benchmark (target_ts, source, predicted, run_at)
VALUES (:target_ts, :source, :predicted, NOW())
ON CONFLICT DO NOTHING
"""


def write_actuals(df: pd.DataFrame) -> int:
    rows = df.to_dict("records")
    if rows:
        execute(UPSERT_ACTUALS, rows)
    return len(rows)


def write_benchmark(df: pd.DataFrame) -> int:
    rows = df[["target_ts", "source", "predicted"]].to_dict("records")
    if rows:
        execute(INSERT_BENCHMARK, rows)
    return len(rows)


def ingest() -> dict:
    """Entry point for the hourly cron."""
    actuals = fetch_recent_actuals()
    cams = fetch_cams_forecast()
    return {
        "actuals_written": write_actuals(actuals),
        "benchmark_written": write_benchmark(cams),
    }


if __name__ == "__main__":
    print(ingest())
