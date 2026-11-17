"""Exporta los marts del warehouse a CSV para Tableau Public."""

from __future__ import annotations

from pathlib import Path

import duckdb


def export_marts(db_path: Path, out_dir: Path) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(db_path), read_only=True) as con:
        tables = [
            row[0]
            for row in con.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'marts' ORDER BY table_name"
            ).fetchall()
        ]
        paths = []
        for table in tables:
            path = out_dir / f"{table}.csv"
            target = str(path.resolve()).replace("'", "''")
            con.execute(f"COPY marts.{table} TO '{target}' (HEADER, DELIMITER ',')")
            paths.append(path)
    return paths
