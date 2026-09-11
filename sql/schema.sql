-- Answers Guiding Question 1: the spine of the whole project.
--
-- The important property: rows land in `forecasts` BEFORE the matching row
-- exists in `actuals`. Error is never computed at write time, it appears
-- later when the join finds a match. That gap is what cannot be faked.

-- What actually happened. One row per hour, filled in as time passes.
CREATE TABLE IF NOT EXISTS actuals (
    ts           TIMESTAMPTZ PRIMARY KEY,
    pm25         DOUBLE PRECISION NOT NULL,
    ingested_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Someone else's forecast for the same hours, so we can tell "my model got
-- worse" apart from "this week was hard for everyone".
CREATE TABLE IF NOT EXISTS benchmark (
    target_ts  TIMESTAMPTZ NOT NULL,
    source     TEXT        NOT NULL,          -- 'cams' or 'naive'
    predicted  DOUBLE PRECISION NOT NULL,
    run_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- run_at deliberately NOT in the key. With NOW() in the primary key every
    -- insert was unique, so the ON CONFLICT DO NOTHING in fetch.py never
    -- fired and each hourly run duplicated every row. One row per hour per
    -- source keeps CAMS's earliest commitment, not its latest revision.
    PRIMARY KEY (target_ts, source)
);

-- Our claims about the future. Written before the answer exists.
CREATE TABLE IF NOT EXISTS forecasts (
    id             BIGSERIAL PRIMARY KEY,
    run_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    target_ts      TIMESTAMPTZ NOT NULL,
    predicted      DOUBLE PRECISION NOT NULL,
    model_version  TEXT NOT NULL,
    horizon_h      INTEGER NOT NULL,
    latency_ms     INTEGER
);

CREATE INDEX IF NOT EXISTS idx_forecasts_target  ON forecasts (target_ts);
CREATE INDEX IF NOT EXISTS idx_forecasts_version ON forecasts (model_version);
CREATE INDEX IF NOT EXISTS idx_benchmark_target  ON benchmark (target_ts);

-- The model registry. One column of `status` replaces MLflow at this scale.
-- Rejected rows stay forever: they are the proof the evaluation gate works.
CREATE TABLE IF NOT EXISTS models (
    version      TEXT PRIMARY KEY,
    trained_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    train_rows   INTEGER NOT NULL,
    holdout_mae  DOUBLE PRECISION NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('active', 'rejected', 'retired')),
    notes        TEXT
);

-- Only one model may be active at a time.
CREATE UNIQUE INDEX IF NOT EXISTS idx_models_one_active
    ON models (status) WHERE status = 'active';

-- Convenience view: forecasts that reality has caught up with.
-- Rows only appear here once the matching actual has been ingested.
CREATE OR REPLACE VIEW scored_forecasts AS
SELECT
    f.id,
    f.run_at,
    f.target_ts,
    f.predicted,
    f.model_version,
    f.horizon_h,
    a.pm25                        AS actual,
    ABS(f.predicted - a.pm25)     AS abs_error
FROM forecasts f
JOIN actuals a ON a.ts = f.target_ts;

-- Forecasts still waiting for reality. Put these on the dashboard: a row for
-- a timestamp that has not happened yet is impossible to fabricate later.
CREATE OR REPLACE VIEW pending_forecasts AS
SELECT f.*
FROM forecasts f
LEFT JOIN actuals a ON a.ts = f.target_ts
WHERE a.ts IS NULL
  AND f.target_ts > NOW();
