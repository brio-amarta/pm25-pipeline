"""The public service. Four endpoints, nothing clever.

/docs comes free from FastAPI. Screenshot it for the README.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from src.config import settings
from src.db import active_model_version, read_sql

app = FastAPI(
    title="PM2.5 Forecast Service",
    description=(
        f"24-hour PM2.5 forecasts for {settings.location_name}. "
        "Every prediction is logged before the real value exists, so accuracy "
        "is measured against reality rather than a held-out split."
    ),
    version="1.0.0",
)


class ForecastPoint(BaseModel):
    target_ts: datetime
    predicted: float
    horizon_h: int


class ForecastResponse(BaseModel):
    location: str
    model_version: str
    generated_at: datetime
    forecast: list[ForecastPoint]


@app.get("/health")
def health() -> dict:
    """Liveness plus data freshness. A 200 with stale data is still a failure."""
    df = read_sql("SELECT MAX(ts) AS latest FROM actuals")
    latest = df.iloc[0]["latest"]
    if latest is None:
        return {"status": "degraded", "reason": "no data ingested yet"}

    age_h = (datetime.now(timezone.utc) - latest).total_seconds() / 3600
    return {
        "status": "ok" if age_h < 3 else "stale",
        "latest_actual": latest,
        "data_age_hours": round(age_h, 2),
        "model_version": active_model_version(),
    }


@app.get("/forecast", response_model=ForecastResponse)
def forecast() -> ForecastResponse:
    df = read_sql(
        """
        SELECT target_ts, predicted, horizon_h, model_version, run_at
        FROM forecasts
        WHERE run_at = (SELECT MAX(run_at) FROM forecasts)
        ORDER BY target_ts
        """
    )
    if df.empty:
        raise HTTPException(503, "No forecasts yet. Has the hourly job run?")

    return ForecastResponse(
        location=settings.location_name,
        model_version=df.iloc[0]["model_version"],
        generated_at=df.iloc[0]["run_at"],
        forecast=[
            ForecastPoint(
                target_ts=r.target_ts, predicted=r.predicted, horizon_h=r.horizon_h
            )
            for r in df.itertuples()
        ],
    )


@app.get("/metrics")
def metrics() -> dict:
    """What the dashboard reads. Error is computed by the join, not at write time."""
    scored = read_sql(
        """
        SELECT AVG(abs_error) AS mae, COUNT(*) AS n
        FROM scored_forecasts
        WHERE target_ts > NOW() - INTERVAL '7 days'
        """
    )
    bench = read_sql(
        """
        SELECT b.source, AVG(ABS(b.predicted - a.pm25)) AS mae
        FROM benchmark b
        JOIN actuals a ON a.ts = b.target_ts
        WHERE b.target_ts > NOW() - INTERVAL '7 days'
        GROUP BY b.source
        """
    )
    pending = read_sql("SELECT COUNT(*) AS n FROM pending_forecasts")

    return {
        "model_version": active_model_version(),
        "mae_7d": round(float(scored.iloc[0]["mae"]), 3)
        if scored.iloc[0]["mae"] is not None
        else None,
        "scored_predictions_7d": int(scored.iloc[0]["n"]),
        "benchmarks": {r.source: round(float(r.mae), 3) for r in bench.itertuples()},
        "pending_forecasts": int(pending.iloc[0]["n"]),
    }


@app.get("/models")
def models() -> list[dict]:
    """Every version, rejected ones included. The gate's audit trail."""
    df = read_sql(
        "SELECT version, trained_at, train_rows, holdout_mae, status, notes "
        "FROM models ORDER BY trained_at DESC"
    )
    return df.to_dict("records")
