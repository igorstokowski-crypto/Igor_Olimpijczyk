"""
db.py — połączenie z Postgres + inicjalizacja schematu.

Zmienna środowiskowa:
  DATABASE_URL  — np. postgresql://user:pass@host:5432/dbname
"""

import os
from contextlib import contextmanager
from pathlib import Path

import psycopg2
import psycopg2.extras

SCHEMA_FILE = Path(__file__).parent / "db" / "schema.sql"


def get_connection():
    return psycopg2.connect(os.environ["DATABASE_URL"])


@contextmanager
def cursor(commit: bool = False):
    """Context manager: daje kursor (dict-like rows), commituje na końcu jeśli commit=True."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            yield cur
        if commit:
            conn.commit()
    finally:
        conn.close()


def init_schema():
    """Tworzy tabele, jeśli jeszcze nie istnieją (idempotentne — CREATE TABLE IF NOT EXISTS)."""
    sql = SCHEMA_FILE.read_text()
    with cursor(commit=True) as cur:
        cur.execute(sql)


if __name__ == "__main__":
    init_schema()
    print("✅ Schemat zainicjalizowany.")
