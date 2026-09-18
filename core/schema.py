from __future__ import annotations

import sqlite3


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS reports (
    report_id TEXT PRIMARY KEY,
    observer_code TEXT NOT NULL,
    zone_id TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    submitted_at TEXT NOT NULL,
    report_mode TEXT NOT NULL CHECK (report_mode IN ('scheduled', 'extra', 'spontaneous', 'followup')),
    odor INTEGER CHECK (odor IN (0, 1)),
    intensity INTEGER NOT NULL CHECK (intensity BETWEEN 0 AND 5),
    odor_type TEXT NOT NULL,
    environment TEXT NOT NULL CHECK (environment IN ('outdoor', 'indoor')),
    confidence TEXT NOT NULL CHECK (confidence IN ('low', 'mid', 'high')),
    saw_forecast INTEGER NOT NULL DEFAULT 0 CHECK (saw_forecast IN (0, 1)),
    memo TEXT DEFAULT '',
    record_origin TEXT NOT NULL DEFAULT 'resident_local',
    idempotency_key TEXT,
    is_sample INTEGER NOT NULL DEFAULT 0 CHECK (is_sample IN (0, 1))
);

CREATE TABLE IF NOT EXISTS weather (
    station_id TEXT NOT NULL,
    weather_at TEXT NOT NULL,
    wd REAL,
    ws REAL,
    temp REAL,
    humidity REAL,
    pressure REAL,
    rain REAL,
    quality_flag TEXT NOT NULL DEFAULT 'ok',
    is_sample INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (station_id, weather_at, is_sample)
);

CREATE TABLE IF NOT EXISTS zones (
    zone_id TEXT NOT NULL,
    name TEXT NOT NULL,
    rep_lat REAL NOT NULL,
    rep_lon REAL NOT NULL,
    boundary_note TEXT DEFAULT '',
    is_sample INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (zone_id, is_sample)
);

CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT NOT NULL,
    name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    is_sample INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (source_id, is_sample)
);

CREATE TABLE IF NOT EXISTS model_runs (
    run_id TEXT PRIMARY KEY,
    run_at TEXT NOT NULL,
    model_name TEXT NOT NULL,
    n_train INTEGER NOT NULL,
    n_test INTEGER NOT NULL,
    n_pos INTEGER NOT NULL,
    accuracy REAL,
    precision REAL,
    recall REAL,
    f1 REAL,
    model_path TEXT,
    is_sample INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS device_log (
    log_id TEXT PRIMARY KEY,
    logged_at TEXT NOT NULL,
    mode TEXT NOT NULL,
    command TEXT,
    acknowledged INTEGER NOT NULL DEFAULT 0,
    risk_level TEXT,
    gas_value REAL,
    outcome TEXT,
    note TEXT DEFAULT ''
);
"""


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(reports)")}
    if "record_origin" not in columns:
        conn.execute("ALTER TABLE reports ADD COLUMN record_origin TEXT NOT NULL DEFAULT 'legacy'")
    if "idempotency_key" not in columns:
        conn.execute("ALTER TABLE reports ADD COLUMN idempotency_key TEXT")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_reports_idempotency ON reports(idempotency_key) WHERE idempotency_key IS NOT NULL")
    conn.commit()
