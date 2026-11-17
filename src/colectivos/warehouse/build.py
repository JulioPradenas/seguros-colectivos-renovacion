"""Construye el warehouse DuckDB: vistas raw sobre parquet y capas staging -> intermediate -> marts."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb

SQL_DIR = Path(__file__).parent / "sql"
SCHEMAS = ("raw", "staging", "intermediate", "marts")
DEFAULT_VALUATION_DATE = date(2025, 12, 31)


def _sql_literal(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def build_warehouse(
    raw_dir: Path,
    db_path: Path,
    sql_dir: Path = SQL_DIR,
    valuation_date: date = DEFAULT_VALUATION_DATE,
) -> None:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(db_path)) as con:
        for schema in SCHEMAS:
            con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        con.execute(f"SET VARIABLE valuation_date = DATE '{valuation_date.isoformat()}'")
        for parquet in sorted(Path(raw_dir).glob("*.parquet")):
            con.execute(
                f"CREATE OR REPLACE VIEW raw.{parquet.stem} AS "
                f"SELECT * FROM read_parquet({_sql_literal(str(parquet.resolve()))})"
            )
        for sql_file in sorted(Path(sql_dir).glob("*/*.sql")):
            con.execute(sql_file.read_text())
