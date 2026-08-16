"""Local read-only HTTP browser for converted Legacy Family Tree databases."""

from __future__ import annotations

import json
import mimetypes
import re
import sqlite3
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from os import PathLike
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from .queries import (
    connect_read_only,
    get_family,
    get_person,
    get_person_facts,
    get_tree,
    list_datasets,
    search_people,
    shortest_relationship_path,
)

_PERSON_ROUTE = re.compile(r"^/api/people/([^/]+)/([^/]+)(?:/(family|facts|tree))?$")


def _identifier(value: str) -> int | str:
    try:
        return int(value)
    except ValueError:
        return value


def _first(parameters: dict[str, list[str]], *names: str) -> str | None:
    for name in names:
        values = parameters.get(name)
        if values:
            return values[0]
    return None


def _handler(database_path: Path, static_root: Path) -> type[BaseHTTPRequestHandler]:
    class RequestHandler(BaseHTTPRequestHandler):
        server_version = "LegacyFamilyTreeReader/0.1"

        def do_GET(self) -> None:
            parsed = urlsplit(self.path)
            if parsed.path.startswith("/api/"):
                self._serve_api(parsed.path, parse_qs(parsed.query, keep_blank_values=True))
            else:
                self._serve_static(parsed.path)

        def _serve_api(self, path: str, parameters: dict[str, list[str]]) -> None:
            try:
                if path == "/api/datasets":
                    self._send_json(list_datasets(database_path))
                    return
                if path == "/api/people/search":
                    dataset = _first(parameters, "dataset", "dataset_id")
                    query = _first(parameters, "q", "query")
                    if dataset is None or query is None:
                        self._bad_request("dataset and q query parameters are required")
                        return
                    limit_text = _first(parameters, "limit") or "50"
                    self._send_json(
                        search_people(
                            database_path,
                            _identifier(dataset),
                            query,
                            limit=int(limit_text),
                        )
                    )
                    return
                if path == "/api/relationship":
                    dataset = _first(parameters, "dataset", "dataset_id")
                    source = _first(
                        parameters,
                        "from",
                        "from_id",
                        "from_person_id",
                        "person1",
                        "person_a",
                    )
                    target = _first(
                        parameters,
                        "to",
                        "to_id",
                        "to_person_id",
                        "person2",
                        "person_b",
                    )
                    if dataset is None or source is None or target is None:
                        self._bad_request("dataset, from, and to query parameters are required")
                        return
                    self._send_json(
                        shortest_relationship_path(
                            database_path,
                            _identifier(dataset),
                            _identifier(source),
                            _identifier(target),
                        )
                    )
                    return

                match = _PERSON_ROUTE.fullmatch(path)
                if not match:
                    self._send_json({"error": "API endpoint not found"}, HTTPStatus.NOT_FOUND)
                    return
                dataset_text, person_text, action = (
                    unquote(value) if value else value for value in match.groups()
                )
                dataset_id = _identifier(dataset_text)
                person_id = _identifier(person_text)
                if action == "family":
                    result = get_family(database_path, dataset_id, person_id)
                elif action == "facts":
                    result = get_person_facts(database_path, dataset_id, person_id)
                elif action == "tree":
                    direction = _first(parameters, "direction") or "ancestors"
                    depth = int(_first(parameters, "max_depth", "generations") or "4")
                    result = get_tree(
                        database_path,
                        dataset_id,
                        person_id,
                        direction=direction,
                        max_depth=depth,
                    )
                else:
                    result = get_person(database_path, dataset_id, person_id)
                if result is None:
                    self._send_json({"error": "Person not found"}, HTTPStatus.NOT_FOUND)
                else:
                    self._send_json(result)
            except (ValueError, TypeError) as error:
                self._bad_request(str(error))
            except (OSError, sqlite3.Error) as error:
                self._send_json(
                    {"error": "Database query failed", "detail": str(error)},
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )

        def _serve_static(self, request_path: str) -> None:
            try:
                decoded = unquote(request_path)
                relative = PurePosixPath(decoded.lstrip("/"))
                if any(part in {"", ".", ".."} for part in relative.parts):
                    raise ValueError
                if decoded.endswith("/") or not relative.parts:
                    relative = relative / "index.html"
                candidate = static_root.joinpath(*relative.parts).resolve()
                candidate.relative_to(static_root)
            except (OSError, ValueError):
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            if not candidate.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            try:
                content = candidate.read_bytes()
            except OSError:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(content)

        def _bad_request(self, message: str) -> None:
            self._send_json({"error": message}, HTTPStatus.BAD_REQUEST)

        def _send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
            content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(content)

    return RequestHandler


def serve(
    database_path: str | PathLike[str],
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> None:
    """Serve package static assets and JSON APIs until interrupted."""

    path = Path(database_path).expanduser().resolve(strict=True)
    connection = connect_read_only(path)
    connection.close()
    static_root = Path(__file__).with_name("static").resolve()
    httpd = ThreadingHTTPServer((host, port), _handler(path, static_root))
    bound_port = httpd.server_address[1]
    browser_host = host if host not in {"", "0.0.0.0", "::"} else "127.0.0.1"
    if ":" in browser_host and not browser_host.startswith("["):
        browser_host = f"[{browser_host}]"
    url = f"http://{browser_host}:{bound_port}/"
    if open_browser:
        timer = threading.Timer(0.1, webbrowser.open, args=(url,))
        timer.daemon = True
        timer.start()
    print(f"Serving Legacy Family Tree browser at {url}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


__all__ = ["serve"]
