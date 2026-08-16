"""Import Legacy 9 FDB/MDB and raw SQLite files into descriptive SQLite."""

from __future__ import annotations

import csv
import hashlib
import math
import re
import shutil
import sqlite3
import subprocess
from collections.abc import Iterable, Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path

from .schema import TABLES, Column, Table, create_schema, quote_identifier

_SQLITE_HEADER = b"SQLite format 3\x00"
_NULL_MARKER = "__LEGACY_MDBTOOLS_NULL_7B748261__"
_INTEGER = re.compile(r"[+-]?\d+")


class ImportError(RuntimeError):
    """Raised when a Legacy source cannot be imported safely."""


def import_database(
    source_path: str | Path,
    output_path: str | Path,
    dataset_name: str | None = None,
    allow_duplicate: bool = False,
) -> int:
    """Transactionally import one Legacy or raw SQLite database.

    Returns the new dataset identifier.  Rows from every import carry this ID,
    so source-local identifiers never collide across datasets.
    """

    source = Path(source_path).expanduser().resolve()
    output = Path(output_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if source == output:
        raise ValueError("source and output database paths must differ")
    source_format = _source_format(source)
    digest = _sha256(source)
    name = dataset_name or source.stem
    legacy_version = _legacy_version(source, source_format)

    output.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(output)
    try:
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        create_schema(connection)
        duplicate = connection.execute(
            "SELECT id FROM datasets WHERE sha256=? ORDER BY id LIMIT 1", (digest,)
        ).fetchone()
        if duplicate and not allow_duplicate:
            raise ImportError(
                f"source SHA-256 already imported as dataset {duplicate[0]}; "
                "pass allow_duplicate=True to import it again"
            )
        cursor = connection.execute(
            """INSERT INTO datasets
               (name, source_path, sha256, imported_at, source_format, legacy_version)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                name,
                str(source),
                digest,
                datetime.now(UTC).isoformat(),
                source_format,
                legacy_version,
            ),
        )
        dataset_id = int(cursor.lastrowid)
        if source_format == "sqlite":
            _import_sqlite(connection, source, dataset_id)
        else:
            _import_mdb(connection, source, dataset_id)
        connection.commit()
        return dataset_id
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def raw_mdb_to_sqlite(
    source_paths: str | Path | Iterable[str | Path], output_path: str | Path
) -> None:
    """Stream one or more FDB/MDB files into a raw ``tbl*`` SQLite database.

    Multiple sources are appended in the supplied order.  This compatibility
    helper intentionally retains Legacy table/column names; use
    :func:`import_database` for dataset-isolated merged databases.
    """

    if isinstance(source_paths, (str, Path)):
        sources = [Path(source_paths)]
    else:
        sources = [Path(path) for path in source_paths]
    if not sources:
        raise ValueError("at least one source path is required")
    sources = [path.expanduser().resolve() for path in sources]
    for source in sources:
        if not source.is_file():
            raise FileNotFoundError(source)
        if _source_format(source) == "sqlite":
            raise ValueError(f"expected an FDB/MDB source, got SQLite: {source}")

    output = Path(output_path).expanduser().resolve()
    if output in sources:
        raise ValueError("source and output database paths must differ")
    output.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(output)
    try:
        connection.execute("BEGIN IMMEDIATE")
        for table in TABLES:
            definitions = ", ".join(
                f"{quote_identifier(column.source_name)} {column.storage_type}"
                for column in table.columns
            )
            connection.execute(
                f"CREATE TABLE IF NOT EXISTS {quote_identifier(table.source_name)} ({definitions})"
            )
        for source in sources:
            available = _mdb_tables(source)
            if not any(table.source_name.casefold() in available for table in TABLES):
                raise ImportError(f"no Legacy 9 tables found in {source}")
            for table in TABLES:
                if table.source_name.casefold() not in available:
                    continue
                header, rows = _mdb_rows(source, table.source_name)
                try:
                    _insert_raw_rows(connection, table, header, rows)
                finally:
                    rows.close()
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def _source_format(path: Path) -> str:
    with path.open("rb") as source:
        header = source.read(len(_SQLITE_HEADER))
    if header == _SQLITE_HEADER:
        return "sqlite"
    if path.suffix.casefold() in {".fdb", ".mdb", ".accdb"}:
        return "fdb" if path.suffix.casefold() == ".fdb" else "mdb"
    raise ImportError(f"unsupported database format: {path}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _legacy_version(path: Path, source_format: str) -> str | None:
    try:
        if source_format == "sqlite":
            connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
            try:
                table_name = _sqlite_source_tables(connection).get("tblhr")
                if not table_name:
                    return None
                row = connection.execute(
                    f"SELECT Setting FROM {quote_identifier(table_name)} "
                    "WHERE Item='LegacyVer' LIMIT 1"
                ).fetchone()
                return None if not row or row[0] is None else str(row[0]).strip()
            finally:
                connection.close()
        if "tblhr" not in _mdb_tables(path):
            return None
        header, rows = _mdb_rows(path, "tblHR")
        try:
            folded = {name.casefold(): index for index, name in enumerate(header)}
            for row in rows:
                if row[folded["item"]] == "LegacyVer":
                    return row[folded["setting"]].strip() or None
        finally:
            rows.close()
    except (ImportError, OSError, sqlite3.Error, KeyError, IndexError):
        return None
    return None


def _import_mdb(connection: sqlite3.Connection, path: Path, dataset_id: int) -> None:
    available = _mdb_tables(path)
    if not any(table.source_name.casefold() in available for table in TABLES):
        raise ImportError(f"no Legacy 9 tables found in {path}")
    for table in TABLES:
        if table.source_name.casefold() not in available:
            continue
        header, rows = _mdb_rows(path, table.source_name)
        try:
            _insert_descriptive_rows(connection, table, header, rows, dataset_id)
        finally:
            rows.close()


def _mdb_tables(path: Path) -> set[str]:
    executable = shutil.which("mdb-tables")
    if executable is None:
        raise ImportError("mdb-tables is required to read FDB/MDB files")
    process = subprocess.run(
        [executable, "-1", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        check=False,
    )
    if process.returncode:
        raise ImportError(f"mdb-tables failed for {path}: {process.stderr.strip()}")
    return {line.strip().casefold() for line in process.stdout.splitlines() if line.strip()}


class _MDBRows(Iterator[list[str]]):
    def __init__(self, process: subprocess.Popen[str], reader: Iterator[list[str]]) -> None:
        self.process = process
        self.reader = reader
        self.closed = False
        self.exhausted = False

    def __iter__(self) -> _MDBRows:
        return self

    def __next__(self) -> list[str]:
        try:
            return next(self.reader)
        except StopIteration:
            self.exhausted = True
            self.close()
            raise

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if not self.exhausted:
            if self.process.stdout:
                self.process.stdout.close()
            if self.process.poll() is None:
                self.process.terminate()
            self.process.wait()
            if self.process.stderr:
                self.process.stderr.close()
            return
        stderr = self.process.stderr.read() if self.process.stderr else ""
        return_code = self.process.wait()
        if self.process.stdout:
            self.process.stdout.close()
        if self.process.stderr:
            self.process.stderr.close()
        if return_code:
            raise ImportError(f"mdb-export failed: {stderr.strip()}")


def _mdb_rows(path: Path, table_name: str) -> tuple[list[str], _MDBRows]:
    executable = shutil.which("mdb-export")
    if executable is None:
        raise ImportError("mdb-export is required to read FDB/MDB files")
    process = subprocess.Popen(
        [executable, "-0", _NULL_MARKER, str(path), table_name],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="strict",
    )
    assert process.stdout is not None
    reader = csv.reader(process.stdout)
    try:
        header = next(reader)
    except StopIteration:
        stderr = process.stderr.read() if process.stderr else ""
        process.wait()
        raise ImportError(f"mdb-export returned no header for {table_name}: {stderr.strip()}")
    return header, _MDBRows(process, reader)


def _import_sqlite(connection: sqlite3.Connection, path: Path, dataset_id: int) -> None:
    source = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    try:
        source_tables = _sqlite_source_tables(source)
        if not any(table.source_name.casefold() in source_tables for table in TABLES):
            raise ImportError(f"no raw Legacy 9 tbl* tables found in {path}")
        for table in TABLES:
            actual_name = source_tables.get(table.source_name.casefold())
            if not actual_name:
                continue
            cursor = source.execute(f"SELECT * FROM {quote_identifier(actual_name)}")
            header = [description[0] for description in cursor.description or ()]
            _insert_descriptive_rows(connection, table, header, _cursor_rows(cursor), dataset_id)
    finally:
        source.close()


def _sqlite_source_tables(connection: sqlite3.Connection) -> dict[str, str]:
    return {
        str(name).casefold(): str(name)
        for (name,) in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'tbl%'"
        )
    }


def _cursor_rows(cursor: sqlite3.Cursor, batch_size: int = 1000) -> Iterator[Sequence[object]]:
    while rows := cursor.fetchmany(batch_size):
        yield from rows


def _column_plan(table: Table, header: Sequence[str]) -> list[tuple[int, Column]]:
    source_columns = {column.source_name.casefold(): column for column in table.columns}
    plan: list[tuple[int, Column]] = []
    unknown: list[str] = []
    seen: set[str] = set()
    for index, source_name in enumerate(header):
        column = source_columns.get(str(source_name).casefold())
        if column is None:
            unknown.append(str(source_name))
        elif column.source_name.casefold() not in seen:
            seen.add(column.source_name.casefold())
            plan.append((index, column))
    if unknown:
        raise ImportError(
            f"{table.source_name} has columns outside the Legacy 9 schema: {', '.join(unknown)}"
        )
    return plan


def _insert_descriptive_rows(
    connection: sqlite3.Connection,
    table: Table,
    header: Sequence[str],
    rows: Iterable[Sequence[object]],
    dataset_id: int,
) -> None:
    plan = _column_plan(table, header)
    if not plan:
        return
    names = ["dataset_id", *(column.name for _, column in plan)]
    sql = (
        f"INSERT INTO {quote_identifier(table.name)} "
        f"({', '.join(quote_identifier(name) for name in names)}) "
        f"VALUES ({', '.join('?' for _ in names)})"
    )
    connection.executemany(
        sql,
        (
            (dataset_id, *(_coerce(row[index], column.storage_type) for index, column in plan))
            for row in rows
        ),
    )


def _insert_raw_rows(
    connection: sqlite3.Connection,
    table: Table,
    header: Sequence[str],
    rows: Iterable[Sequence[object]],
) -> None:
    plan = _column_plan(table, header)
    if not plan:
        return
    names = [column.source_name for _, column in plan]
    sql = (
        f"INSERT INTO {quote_identifier(table.source_name)} "
        f"({', '.join(quote_identifier(name) for name in names)}) "
        f"VALUES ({', '.join('?' for _ in names)})"
    )
    connection.executemany(
        sql,
        (tuple(_coerce(row[index], column.storage_type) for index, column in plan) for row in rows),
    )


def _coerce(value: object, storage_type: str) -> object:
    if value is None or value == _NULL_MARKER:
        return None
    if storage_type == "TEXT":
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="surrogateescape")
        return str(value)
    if storage_type == "INTEGER":
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value) if value.is_integer() else value
        text = str(value)
        if _INTEGER.fullmatch(text):
            try:
                return int(text)
            except ValueError:
                pass
        return value
    if storage_type == "REAL":
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
        text = str(value)
        try:
            converted = float(text)
        except ValueError:
            return value
        return converted if math.isfinite(converted) else value
    return value


__all__ = ["ImportError", "import_database", "raw_mdb_to_sqlite"]
