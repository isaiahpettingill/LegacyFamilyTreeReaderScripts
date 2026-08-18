from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from legacy_family_tree_reader.queries import connect_read_only
from legacy_family_tree_reader.server import _handler
from legacy_family_tree_reader.site import build_static_site


@contextmanager
def _running_server(
    database: Path, static_root: Path, data_root: Path | None = None
) -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(database, static_root, data_root))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _get(url: str) -> tuple[int, dict[str, str], bytes]:
    with urlopen(url, timeout=2) as response:
        return response.status, dict(response.headers), response.read()


def test_http_api_static_files_and_traversal_security(tmp_path: Path, merged_db: Path) -> None:
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("synthetic home", encoding="ascii")
    (static / "app.js").write_text("const synthetic = true;", encoding="ascii")
    secret = tmp_path / "secret.txt"
    secret.write_text("not public", encoding="ascii")

    with _running_server(merged_db, static.resolve()) as base:
        status, headers, body = _get(f"{base}/")
        assert status == 200
        assert body == b"synthetic home"
        assert headers["X-Content-Type-Options"] == "nosniff"

        status, headers, body = _get(f"{base}/api/datasets")
        assert status == 200
        assert headers["Cache-Control"] == "no-store"
        assert len(json.loads(body)) == 2

        _, _, body = _get(f"{base}/api/people/search?dataset=1&q=harbor%20morgan")
        assert [person["person_id"] for person in json.loads(body)] == [3]
        _, _, body = _get(f"{base}/api/people?dataset=1&limit=2&offset=2")
        page = json.loads(body)
        assert page["total"] == 6
        assert len(page["people"]) == 2
        assert page["offset"] == 2
        _, _, body = _get(f"{base}/api/people/1/3/family")
        assert json.loads(body)["person"]["person_id"] == 3

        for path in ("/%2e%2e/secret.txt", "/..%2fsecret.txt", "/missing.txt"):
            with pytest.raises(HTTPError) as error:
                _get(base + path)
            assert error.value.code == 404
        with pytest.raises(HTTPError) as error:
            _get(f"{base}/api/people/search?q=missing-dataset")
        assert error.value.code == 400
        with pytest.raises(HTTPError) as error:
            urlopen(Request(f"{base}/api/datasets", method="POST"), timeout=2)
        assert error.value.code == 501


def test_read_only_connection_rejects_writes(merged_db: Path) -> None:
    connection = connect_read_only(merged_db)
    try:
        assert connection.execute("PRAGMA query_only").fetchone() == (1,)
        with pytest.raises(sqlite3.OperationalError, match="readonly|read-only"):
            connection.execute("DELETE FROM datasets")
    finally:
        connection.close()


def test_http_chunk_manifest_part_head_and_spa_fallback(tmp_path: Path, merged_db: Path) -> None:
    output = tmp_path / "site"
    build_static_site(merged_db, output, chunk_size=4096)
    manifest = json.loads((output / "data" / "manifest.json").read_text(encoding="utf-8"))
    part_name = manifest["parts"][0]["path"]

    with _running_server(merged_db, output, output / "data") as base:
        status, headers, body = _get(f"{base}/data/manifest.json")
        assert status == 200
        assert headers["Content-Type"] == "application/json"
        assert headers["Cache-Control"] == "no-store"
        assert int(headers["Content-Length"]) == len(body)
        assert json.loads(body) == manifest

        status, headers, body = _get(f"{base}/data/{part_name}")
        assert status == 200
        assert headers["Content-Type"] == "application/octet-stream"
        assert headers["Cache-Control"] == "public, max-age=31536000, immutable"
        assert int(headers["Content-Length"]) == len(body)

        with urlopen(Request(f"{base}/data/{part_name}", method="HEAD"), timeout=2) as response:
            assert response.status == 200
            assert response.read() == b""
            assert int(response.headers["Content-Length"]) == len(body)

        _, _, index = _get(f"{base}/")
        _, _, spa = _get(f"{base}/dataset/1/person/16")
        assert spa == index
        _, _, trailing_spa = _get(f"{base}/dataset/1/")
        assert trailing_spa == index

        with pytest.raises(HTTPError) as error:
            _get(f"{base}/data/%2e%2e/secret.txt")
        assert error.value.code == 404


def test_packaged_standalone_browser_assets_are_present() -> None:
    from legacy_family_tree_reader import server

    static = Path(server.__file__).with_name("static")
    assert (static / "standalone.js").is_file()
    assert (static / "vendor" / "sql-asm.js").stat().st_size > 1_000_000
    assert (static / "vendor" / "sql.js.LICENSE").is_file()

    app = (static / "app.js").read_text(encoding="utf-8")
    assert "elements.searchInput.disabled = !ready;" in app
    assert "elements.searchInput.disabled = !ready || busy;" not in app
    assert 'if (["0", "m", "male"].includes(code)) return "M";' in app
    assert 'if (["1", "f", "female"].includes(code)) return "F";' in app
