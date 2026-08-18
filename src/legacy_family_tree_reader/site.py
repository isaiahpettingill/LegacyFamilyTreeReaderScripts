"""Build and cache static sites backed by streamed SQLite chunks."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from os import PathLike
from pathlib import Path
from typing import Any

from .queries import connect_read_only

MIB = 1024 * 1024
DEFAULT_CHUNK_SIZE = 8 * MIB
MAX_CHUNK_SIZE = 24 * MIB
_COPY_BUFFER_SIZE = MIB
_FORMAT = "legacy-family-tree-reader-chunks"
_DATABASE_NAME = "family-tree.sqlite"
_MANIFEST_NAME = "manifest.json"
_SQLITE_SIGNATURE = b"SQLite format 3\x00"


def _validate_chunk_size(chunk_size: int) -> None:
    if isinstance(chunk_size, bool) or not isinstance(chunk_size, int):
        raise TypeError("chunk size must be an integer number of bytes")
    if chunk_size <= 0:
        raise ValueError("chunk size must be greater than zero")
    if chunk_size > MAX_CHUNK_SIZE:
        raise ValueError("chunk size must not exceed 24 MiB")


def _validate_database(database: str | PathLike[str]) -> Path:
    path = Path(database).expanduser().resolve(strict=True)
    if not path.is_file():
        raise ValueError(f"database is not a file: {path}")
    with path.open("rb") as source:
        if source.read(len(_SQLITE_SIGNATURE)) != _SQLITE_SIGNATURE:
            raise ValueError(f"not a SQLite database: {path}")

    connection = connect_read_only(path)
    try:
        tables = {
            str(row[0]).casefold()
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            )
        }
        missing = {"datasets", "individuals"} - tables
        if missing:
            names = ", ".join(sorted(missing))
            raise ValueError(f"database is not a descriptive dataset (missing: {names})")
        connection.execute("SELECT 1 FROM datasets LIMIT 0")
        connection.execute("SELECT 1 FROM individuals LIMIT 0")
    finally:
        connection.close()
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(_COPY_BUFFER_SIZE):
            digest.update(block)
    return digest.hexdigest()


def _part_name(index: int) -> str:
    return f"{_DATABASE_NAME}.part{index:03d}"


def _write_chunks(database: Path, data_root: Path, chunk_size: int) -> dict[str, Any]:
    data_root.mkdir()
    full_digest = hashlib.sha256()
    total_size = 0
    parts: list[dict[str, Any]] = []

    with database.open("rb") as source:
        index = 0
        while True:
            first = source.read(min(_COPY_BUFFER_SIZE, chunk_size))
            if not first:
                break
            part_path = data_root / _part_name(index)
            part_digest = hashlib.sha256()
            part_size = 0
            with part_path.open("xb") as part:
                block = first
                while block:
                    part.write(block)
                    part_digest.update(block)
                    full_digest.update(block)
                    block_size = len(block)
                    part_size += block_size
                    total_size += block_size
                    remaining = chunk_size - part_size
                    if not remaining:
                        break
                    block = source.read(min(_COPY_BUFFER_SIZE, remaining))
            parts.append(
                {
                    "path": part_path.name,
                    "size": part_size,
                    "sha256": part_digest.hexdigest(),
                }
            )
            index += 1

    manifest: dict[str, Any] = {
        "format": _FORMAT,
        "version": 1,
        "database": _DATABASE_NAME,
        "size": total_size,
        "sha256": full_digest.hexdigest(),
        "chunk_size": chunk_size,
        "parts": parts,
    }
    manifest_path = data_root / _MANIFEST_NAME
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=True, indent=2, separators=(",", ": ")) + "\n",
        encoding="utf-8",
    )
    return manifest


def _paths_overlap(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def _replace_directory(staging: Path, destination: Path) -> None:
    if not destination.exists():
        os.replace(staging, destination)
        return

    backup = Path(tempfile.mkdtemp(prefix=f".{destination.name}.old-", dir=destination.parent))
    backup.rmdir()
    os.replace(destination, backup)
    try:
        os.replace(staging, destination)
    except BaseException:
        os.replace(backup, destination)
        raise
    shutil.rmtree(backup)


def _new_staging_directory(parent: Path, name: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=f".{name}.tmp-", dir=parent))


def build_static_site(
    database: str | PathLike[str],
    output_dir: str | PathLike[str],
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    force: bool = False,
) -> dict[str, Any]:
    """Build a complete static browser and chunked database atomically."""

    _validate_chunk_size(chunk_size)
    database_path = _validate_database(database)
    output = Path(output_dir).expanduser().resolve()
    static_root = Path(__file__).with_name("static").resolve(strict=True)
    if _paths_overlap(database_path, output):
        raise ValueError("source database and output directory cannot overlap")
    if _paths_overlap(static_root, output):
        raise ValueError("packaged static files and output directory cannot overlap")
    if output.exists() and not output.is_dir():
        raise ValueError(f"output exists and is not a directory: {output}")
    if output.exists() and any(output.iterdir()) and not force:
        raise ValueError(f"output directory is not empty: {output}; use --force to replace it")

    output.parent.mkdir(parents=True, exist_ok=True)
    staging = _new_staging_directory(output.parent, output.name)
    try:
        shutil.copytree(static_root, staging, dirs_exist_ok=True)
        manifest = _write_chunks(database_path, staging / "data", chunk_size)
        _replace_directory(staging, output)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    return {
        "output": str(output),
        "data": str(output / "data"),
        "manifest_path": str(output / "data" / _MANIFEST_NAME),
        "manifest": manifest,
    }


def _valid_cached_data(data_root: Path, expected_sha256: str, expected_size: int) -> bool:
    try:
        manifest = json.loads((data_root / _MANIFEST_NAME).read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            return False
        chunk_size = manifest.get("chunk_size")
        _validate_chunk_size(chunk_size)
        if (
            manifest.get("format") != _FORMAT
            or manifest.get("version") != 1
            or manifest.get("database") != _DATABASE_NAME
            or manifest.get("size") != expected_size
            or manifest.get("sha256") != expected_sha256
        ):
            return False
        parts = manifest.get("parts")
        if not isinstance(parts, list) or not parts:
            return False

        full_digest = hashlib.sha256()
        total_size = 0
        for index, metadata in enumerate(parts):
            if not isinstance(metadata, dict) or metadata.get("path") != _part_name(index):
                return False
            declared_size = metadata.get("size")
            declared_sha256 = metadata.get("sha256")
            if (
                not isinstance(declared_size, int)
                or declared_size <= 0
                or declared_size > chunk_size
                or not isinstance(declared_sha256, str)
            ):
                return False
            if index < len(parts) - 1 and declared_size != chunk_size:
                return False
            part_path = data_root / metadata["path"]
            if not part_path.is_file() or part_path.stat().st_size != declared_size:
                return False
            part_digest = hashlib.sha256()
            with part_path.open("rb") as part:
                while block := part.read(_COPY_BUFFER_SIZE):
                    part_digest.update(block)
                    full_digest.update(block)
                    total_size += len(block)
            if part_digest.hexdigest() != declared_sha256:
                return False
        return total_size == expected_size and full_digest.hexdigest() == expected_sha256
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False


def ensure_chunk_cache(database: str | PathLike[str]) -> Path:
    """Return a verified hash-addressed data directory for a database."""

    database_path = _validate_database(database)
    expected_size = database_path.stat().st_size
    expected_sha256 = _sha256(database_path)
    sites_root = Path.home() / ".cache" / "legacy-family-tree-reader" / "sites"
    cache_root = sites_root / expected_sha256
    data_root = cache_root / "data"
    if _valid_cached_data(data_root, expected_sha256, expected_size):
        return data_root

    sites_root.mkdir(parents=True, exist_ok=True)
    staging = _new_staging_directory(sites_root, expected_sha256)
    try:
        manifest = _write_chunks(database_path, staging / "data", DEFAULT_CHUNK_SIZE)
        if manifest["sha256"] != expected_sha256 or manifest["size"] != expected_size:
            raise OSError("database changed while its chunk cache was being built")
        try:
            _replace_directory(staging, cache_root)
        except OSError:
            if _valid_cached_data(data_root, expected_sha256, expected_size):
                shutil.rmtree(staging, ignore_errors=True)
                return data_root
            raise
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return data_root


__all__ = [
    "DEFAULT_CHUNK_SIZE",
    "MAX_CHUNK_SIZE",
    "build_static_site",
    "ensure_chunk_cache",
]
