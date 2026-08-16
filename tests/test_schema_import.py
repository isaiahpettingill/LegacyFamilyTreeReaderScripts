from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest

from legacy_family_tree_reader.importer import ImportError, import_database
from legacy_family_tree_reader.schema import TABLES, create_schema


def test_complete_schema_catalog_and_descriptive_metadata() -> None:
    assert len(TABLES) == 38
    assert sum(len(table.columns) for table in TABLES) == 522
    assert len({table.source_name for table in TABLES}) == 38
    assert len({table.name for table in TABLES}) == 38
    assert all(table.source_name.startswith("tbl") and table.description for table in TABLES)
    assert all(
        column.source_name
        and column.name
        and column.description
        and column.storage_type in {"INTEGER", "REAL", "TEXT"}
        for table in TABLES
        for column in table.columns
    )

    connection = sqlite3.connect(":memory:")
    create_schema(connection)
    assert connection.execute("SELECT count(*) FROM schema_metadata").fetchone()[0] == 38
    assert connection.execute("SELECT count(*) FROM schema_columns").fetchone()[0] == 522
    assert connection.execute(
        "SELECT description FROM schema_metadata WHERE source_table='tblIR'"
    ).fetchone() == ("Individual people",)
    assert connection.execute(
        """SELECT column_name, storage_type, description
           FROM schema_columns WHERE source_table='tblIR' AND source_column='GivenName'"""
    ).fetchone() == ("given_name", "TEXT", "Given name")
    application_tables = {
        row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {table.name for table in TABLES} <= application_tables


def test_import_merge_isolates_local_ids_and_rejects_duplicate_hashes(
    tmp_path: Path, raw_factory: Callable[..., Path]
) -> None:
    first = raw_factory(marker="first")
    second = raw_factory(marker="second")
    output = tmp_path / "merged.sqlite"

    first_id = import_database(first, output, "First")
    second_id = import_database(second, output, "Second")
    assert (first_id, second_id) == (1, 2)

    connection = sqlite3.connect(output)
    assert connection.execute(
        "SELECT dataset_id, individual_id FROM individuals ORDER BY dataset_id, individual_id"
    ).fetchall()[:2] == [(1, 1), (1, 2)]
    assert connection.execute(
        "SELECT count(*) FROM individuals WHERE individual_id=1"
    ).fetchone() == (2,)
    before = connection.execute("SELECT count(*) FROM datasets").fetchone()[0]
    connection.close()

    with pytest.raises(ImportError, match="SHA-256 already imported as dataset 1"):
        import_database(first, output)
    with sqlite3.connect(output) as connection:
        assert connection.execute("SELECT count(*) FROM datasets").fetchone()[0] == before

    duplicate_id = import_database(first, output, allow_duplicate=True)
    assert duplicate_id == 3
    with sqlite3.connect(output) as connection:
        assert (
            connection.execute("SELECT count(*) FROM individuals WHERE dataset_id=3").fetchone()[0]
            == 6
        )


def test_import_rejects_unknown_raw_columns_transactionally(
    tmp_path: Path, raw_factory: Callable[..., Path]
) -> None:
    source = raw_factory(marker="unknown")
    with sqlite3.connect(source) as connection:
        connection.execute("ALTER TABLE tblIR ADD COLUMN NotLegacy9 TEXT")
    output = tmp_path / "output.sqlite"

    with pytest.raises(ImportError, match="columns outside the Legacy 9 schema: NotLegacy9"):
        import_database(source, output)

    with sqlite3.connect(output) as connection:
        assert connection.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table'"
        ).fetchone() == (0,)
