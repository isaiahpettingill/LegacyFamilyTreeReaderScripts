from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from legacy_family_tree_reader import cli
from legacy_family_tree_reader.site import (
    MAX_CHUNK_SIZE,
    build_static_site,
    ensure_chunk_cache,
)


def _manifest(output: Path) -> dict[str, object]:
    return json.loads((output / "data" / "manifest.json").read_text(encoding="utf-8"))


def _joined_parts(data_root: Path, manifest: dict[str, object]) -> bytes:
    parts = manifest["parts"]
    assert isinstance(parts, list)
    return b"".join((data_root / part["path"]).read_bytes() for part in parts)


def test_build_static_site_chunks_are_exact_and_deterministic(
    tmp_path: Path, merged_db: Path
) -> None:
    output = tmp_path / "site"
    result = build_static_site(merged_db, output, chunk_size=4096)
    manifest = _manifest(output)
    source = merged_db.read_bytes()

    assert result["manifest"] == manifest
    assert manifest["format"] == "legacy-family-tree-reader-chunks"
    assert manifest["version"] == 1
    assert manifest["database"] == "family-tree.sqlite"
    assert manifest["size"] == len(source)
    assert manifest["sha256"] == hashlib.sha256(source).hexdigest()
    assert manifest["chunk_size"] == 4096
    assert _joined_parts(output / "data", manifest) == source

    parts = manifest["parts"]
    assert isinstance(parts, list)
    for index, part in enumerate(parts):
        content = (output / "data" / part["path"]).read_bytes()
        assert part["path"] == f"family-tree.sqlite.part{index:03d}"
        assert part["size"] == len(content)
        assert part["sha256"] == hashlib.sha256(content).hexdigest()
    assert (output / "vendor" / "sql.js.LICENSE").is_file()

    first_manifest = (output / "data" / "manifest.json").read_bytes()
    build_static_site(merged_db, output, chunk_size=4096, force=True)
    assert (output / "data" / "manifest.json").read_bytes() == first_manifest


def test_build_static_site_rejects_invalid_inputs_without_replacing_output(
    tmp_path: Path, merged_db: Path
) -> None:
    output = tmp_path / "existing"
    output.mkdir()
    marker = output / "keep.txt"
    marker.write_text("keep", encoding="ascii")

    with pytest.raises(ValueError, match="not empty"):
        build_static_site(merged_db, output)
    assert marker.read_text(encoding="ascii") == "keep"

    for size in (0, -1, MAX_CHUNK_SIZE + 1):
        with pytest.raises(ValueError, match="chunk size"):
            build_static_site(merged_db, tmp_path / f"invalid-{size}", chunk_size=size)

    invalid = tmp_path / "invalid.sqlite"
    invalid.write_bytes(b"not sqlite")
    with pytest.raises(ValueError, match="not a SQLite"):
        build_static_site(invalid, tmp_path / "invalid-site")

    raw_sqlite = tmp_path / "raw.sqlite"
    with sqlite3.connect(raw_sqlite) as connection:
        connection.execute("CREATE TABLE unrelated (value TEXT)")
    with pytest.raises(ValueError, match="descriptive dataset"):
        build_static_site(raw_sqlite, tmp_path / "raw-site")

    with pytest.raises(ValueError, match="cannot overlap"):
        build_static_site(merged_db, merged_db.parent, force=True)
    assert merged_db.is_file()


def test_chunk_cache_is_hash_addressed_reused_and_repairs_corruption(
    tmp_path: Path, merged_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    data_root = ensure_chunk_cache(merged_db)
    source_sha256 = hashlib.sha256(merged_db.read_bytes()).hexdigest()
    assert data_root == (
        tmp_path
        / "home"
        / ".cache"
        / "legacy-family-tree-reader"
        / "sites"
        / source_sha256
        / "data"
    )
    manifest_path = data_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    original_mtime = manifest_path.stat().st_mtime_ns

    assert ensure_chunk_cache(merged_db) == data_root
    assert manifest_path.stat().st_mtime_ns == original_mtime

    first_part = data_root / manifest["parts"][0]["path"]
    first_part.write_bytes(b"x" * first_part.stat().st_size)
    assert ensure_chunk_cache(merged_db) == data_root
    repaired_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert _joined_parts(data_root, repaired_manifest) == merged_db.read_bytes()


def test_build_site_cli_emits_json_and_validates_mib_size(
    tmp_path: Path,
    merged_db: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "cli-site"
    assert cli.main(["build-site", str(merged_db), str(output), "--chunk-size", "1"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["output"] == str(output.resolve())
    assert payload["manifest"]["chunk_size"] == 1024 * 1024

    assert cli.main(["build-site", str(merged_db), str(output), "--chunk-size", "25"]) == 1
    assert "must not exceed 24 MiB" in capsys.readouterr().err
