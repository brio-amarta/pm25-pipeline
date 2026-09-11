"""Database helpers. Thin on purpose.

The engine is created lazily. Building it at import time means every module
needs a working driver and connection string just to be imported, which
breaks tests, breaks `--help`, and turns a missing dependency into an
import-time crash a long way from its cause.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from src.config import settings


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return create_engine(settings.database_url, pool_pre_ping=True)


def init_schema(schema_path: str = "sql/schema.sql") -> None:
    """Run schema.sql. Safe to call repeatedly.

    exec_driver_sql, not text(): the latter parses `:name` as a bind
    parameter, which mangles any SQL containing a colon.
    """
    sql = Path(schema_path).read_text()
    with get_engine().begin() as conn:
        conn.exec_driver_sql(sql)


def read_sql(query: str, **params) -> pd.DataFrame:
    with get_engine().connect() as conn:
        return pd.read_sql(text(query), conn, params=params)


def execute(query: str, rows: list[dict] | dict) -> None:
    with get_engine().begin() as conn:
        conn.execute(text(query), rows)


def load_actuals(limit_hours: int | None = None) -> pd.DataFrame:
    """Actuals in chronological order, indexed by timestamp."""
    df = read_sql("SELECT ts, pm25 FROM actuals ORDER BY ts")
    if limit_hours:
        df = df.tail(limit_hours)
    return df.set_index("ts")


def active_model_version() -> str | None:
    df = read_sql("SELECT version FROM models WHERE status = 'active' LIMIT 1")
    return None if df.empty else df.iloc[0]["version"]
