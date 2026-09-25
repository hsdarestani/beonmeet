import os
import sqlite3
from pathlib import Path
from typing import Any

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()


class CompatConnection:
    def __init__(self, raw: Any, postgres: bool):
        self.raw = raw
        self.postgres = postgres

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self.raw.commit()
            else:
                self.raw.rollback()
        finally:
            self.raw.close()
        return False

    def execute(self, sql: str, params: tuple | list = ()):
        if self.postgres:
            sql = sql.replace("?", "%s")
        return self.raw.execute(sql, params)

    def executescript(self, script: str):
        if not self.postgres:
            return self.raw.executescript(script)
        for statement in script.split(";"):
            statement = statement.strip()
            if statement:
                self.raw.execute(statement)


def is_postgres() -> bool:
    return bool(DATABASE_URL)


def connect_db(sqlite_path: Path) -> CompatConnection:
    if DATABASE_URL:
        import psycopg
        from psycopg.rows import dict_row

        raw = psycopg.connect(
            DATABASE_URL,
            row_factory=dict_row,
            connect_timeout=5,
        )
        return CompatConnection(raw, postgres=True)

    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    raw = sqlite3.connect(sqlite_path, timeout=10)
    raw.row_factory = sqlite3.Row
    return CompatConnection(raw, postgres=False)
