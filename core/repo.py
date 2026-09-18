from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import uuid

import pandas as pd

from .schema import init_db


TABLE_COLUMNS = {
    "reports": ["report_id", "observer_code", "zone_id", "observed_at", "submitted_at", "report_mode", "odor", "intensity", "odor_type", "environment", "confidence", "saw_forecast", "memo", "record_origin", "idempotency_key", "is_sample"],
    "weather": ["station_id", "weather_at", "wd", "ws", "temp", "humidity", "pressure", "rain", "quality_flag", "is_sample"],
    "zones": ["zone_id", "name", "rep_lat", "rep_lon", "boundary_note", "is_sample"],
    "sources": ["source_id", "name", "source_type", "lat", "lon", "is_sample"],
    "model_runs": ["run_id", "run_at", "model_name", "n_train", "n_test", "n_pos", "accuracy", "precision", "recall", "f1", "model_path", "is_sample"],
    "device_log": ["log_id", "logged_at", "mode", "command", "acknowledged", "risk_level", "gas_value", "outcome", "note"],
}


class Repository(ABC):
    """저장소 교체를 위한 최소 인터페이스."""

    @abstractmethod
    def read(self, table: str, sample: bool | None = None) -> pd.DataFrame: ...

    @abstractmethod
    def replace(self, table: str, frame: pd.DataFrame, sample: bool) -> None: ...

    @abstractmethod
    def insert(self, table: str, row: dict) -> None: ...


class SQLiteRepository(Repository):
    def __init__(self, path: str | Path = "data/odor.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            init_db(conn)

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def read(self, table: str, sample: bool | None = None) -> pd.DataFrame:
        self._check_table(table)
        query = f"SELECT * FROM {table}"
        params: tuple = ()
        if sample is not None and "is_sample" in TABLE_COLUMNS[table]:
            query += " WHERE is_sample = ?"
            params = (int(sample),)
        with self.connection() as conn:
            return pd.read_sql_query(query, conn, params=params)

    def replace(self, table: str, frame: pd.DataFrame, sample: bool) -> None:
        self._check_table(table)
        data = frame.copy()
        if "is_sample" in TABLE_COLUMNS[table]:
            data["is_sample"] = int(sample)
        data = data[[c for c in TABLE_COLUMNS[table] if c in data.columns]]
        with self.connection() as conn:
            if "is_sample" in TABLE_COLUMNS[table]:
                conn.execute(f"DELETE FROM {table} WHERE is_sample = ?", (int(sample),))
            else:
                conn.execute(f"DELETE FROM {table}")
            data.to_sql(table, conn, if_exists="append", index=False)

    def insert(self, table: str, row: dict) -> None:
        self._check_table(table)
        values = {k: v for k, v in row.items() if k in TABLE_COLUMNS[table]}
        columns = ", ".join(values)
        placeholders = ", ".join("?" for _ in values)
        with self.connection() as conn:
            conn.execute(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", tuple(values.values()))

    def save_observation(self, observation: dict) -> bool:
        """멱등 키가 이미 있으면 False, 새로 저장하면 True."""
        try:
            self.insert("reports", observation)
            return True
        except sqlite3.IntegrityError as exc:
            if "idempotency" in str(exc).lower() or "unique" in str(exc).lower():
                return False
            raise

    def get_recent_observations(self, limit: int = 100, sample: bool | None = None) -> pd.DataFrame:
        frame = self.read("reports", sample=sample)
        if frame.empty:
            return frame
        return frame.sort_values("observed_at", ascending=False).head(limit)

    def get_observations_by_participant(self, participant_id: str, limit: int = 20) -> pd.DataFrame:
        with self.connection() as conn:
            return pd.read_sql_query(
                "SELECT * FROM reports WHERE observer_code = ? ORDER BY observed_at DESC LIMIT ?",
                conn, params=(participant_id, int(limit)),
            )

    def get_window_aggregates(self, sample: bool | None = None) -> pd.DataFrame:
        from .features import make_windows
        return make_windows(self.read('reports',sample),self.read('weather',sample),
                            self.read('zones',sample),self.read('sources',sample))

    @staticmethod
    def _check_table(table: str) -> None:
        if table not in TABLE_COLUMNS:
            raise ValueError(f"허용되지 않은 테이블: {table}")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"
