"""Read-only FastAPI browser for converted Legacy Family Tree databases."""

from __future__ import annotations

import hashlib
import hmac
import html
import os
import sqlite3
import threading
import time
import webbrowser
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from http import HTTPStatus
from os import PathLike
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response

from .queries import (
    connect_read_only,
    get_family,
    get_person,
    get_person_facts,
    get_tree,
    list_datasets,
    list_people,
    search_people,
    shortest_relationship_path,
)

_SESSION_COOKIE = "family_session"
_SESSION_SECONDS = 12 * 60 * 60
_PUBLIC_PATHS = frozenset({"/healthz", "/robots.txt", "/login", "/logout"})
_SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self' "
        "'sha256-gejFXlVGkHnHkHvZFnQIzXSbpHGolD/d8fGODE3oV0o='; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; "
        "font-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'; "
        "object-src 'none'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-Robots-Tag": "noindex, nofollow, noarchive",
}
_LOGIN_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex, nofollow, noarchive">
  <title>Family Archive Login</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 28rem; margin: 12vh auto; padding: 1rem; }
    form { display: grid; gap: 1rem; }
    input, button { box-sizing: border-box; font: inherit; padding: .75rem; width: 100%; }
    .error { color: #8b1a1a; }
  </style>
</head>
<body>
  <main>
    <h1>Family Archive</h1>
    {error}
    <form action="/login" method="post">
      <input name="next" type="hidden" value="{next_path}">
      <label>Password <input name="password" type="password" required autofocus></label>
      <button type="submit">Sign in</button>
    </form>
  </main>
</body>
</html>
"""


def _identifier(value: str) -> int | str:
    try:
        return int(value)
    except ValueError:
        return value


def _parameters(request: Request) -> dict[str, list[str]]:
    parameters: dict[str, list[str]] = {}
    for name, value in request.query_params.multi_items():
        parameters.setdefault(name, []).append(value)
    return parameters


def _first(parameters: dict[str, list[str]], *names: str) -> str | None:
    for name in names:
        values = parameters.get(name)
        if values:
            return values[0]
    return None


def _json(payload: Any, status: HTTPStatus = HTTPStatus.OK) -> JSONResponse:
    return JSONResponse(
        payload,
        status_code=int(status),
        headers={"Cache-Control": "no-store"},
    )


def _api_call(callback: Callable[[], Any], *, missing_person: bool = False) -> JSONResponse:
    try:
        payload = callback()
        if missing_person and payload is None:
            return _json({"error": "Person not found"}, HTTPStatus.NOT_FOUND)
        return _json(payload)
    except (ValueError, TypeError) as error:
        return _json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
    except (OSError, sqlite3.Error) as error:
        return _json(
            {"error": "Database query failed", "detail": str(error)},
            HTTPStatus.INTERNAL_SERVER_ERROR,
        )


def _session_token(secret: str) -> str:
    expires = str(int(time.time()) + _SESSION_SECONDS)
    signature = hmac.new(secret.encode(), expires.encode(), hashlib.sha256).hexdigest()
    return f"{expires}.{signature}"


def _valid_session(token: str | None, secret: str) -> bool:
    if not token:
        return False
    try:
        expires_text, signature = token.split(".", 1)
        expires = int(expires_text)
    except (TypeError, ValueError):
        return False
    expected = hmac.new(secret.encode(), expires_text.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected) and int(time.time()) <= expires


def _password_matches(candidate: str, expected: str) -> bool:
    candidate_digest = hashlib.sha256(candidate.encode()).digest()
    expected_digest = hashlib.sha256(expected.encode()).digest()
    return hmac.compare_digest(candidate_digest, expected_digest)


def _safe_next(value: str | None) -> str:
    if (
        not value
        or not value.startswith("/")
        or value.startswith("//")
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        return "/"
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.path in {"/login", "/logout"}:
        return "/"
    return parsed.path + (f"?{parsed.query}" if parsed.query else "")


def _login_page(*, invalid: bool = False, next_path: str = "/") -> HTMLResponse:
    error = '<p class="error" role="alert">Invalid password.</p>' if invalid else ""
    content = _LOGIN_PAGE.replace("{error}", error).replace(
        "{next_path}", html.escape(_safe_next(next_path), quote=True)
    )
    return HTMLResponse(
        content,
        status_code=HTTPStatus.UNAUTHORIZED if invalid else HTTPStatus.OK,
        headers={"Cache-Control": "no-store"},
    )


def create_app(
    database_path: str | PathLike[str],
    password: str | None = None,
    session_secret: str | None = None,
    secure_cookie: bool = False,
) -> FastAPI:
    """Create a read-only API and packaged browser application."""

    path = Path(database_path).expanduser().resolve()
    static_root = Path(__file__).with_name("static").resolve()
    if password is not None and not session_secret:
        raise ValueError("session_secret is required when password is configured")

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        connection = connect_read_only(path)
        try:
            connection.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
        finally:
            connection.close()
        yield

    app = FastAPI(
        title="Legacy Family Tree Reader",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def security_and_authentication(request: Request, call_next: Callable[..., Any]) -> Any:
        if password is not None and request.url.path not in _PUBLIC_PATHS:
            assert session_secret is not None
            if not _valid_session(request.cookies.get(_SESSION_COOKIE), session_secret):
                if request.url.path.startswith("/api/"):
                    response = _json({"error": "Authentication required"}, HTTPStatus.UNAUTHORIZED)
                else:
                    destination = request.url.path
                    if request.url.query:
                        destination += f"?{request.url.query}"
                    response = HTMLResponse(
                        status_code=HTTPStatus.SEE_OTHER,
                        headers={
                            "Location": f"/login?{urlencode({'next': destination})}",
                            "Cache-Control": "no-store",
                        },
                    )
                for name, value in _SECURITY_HEADERS.items():
                    response.headers[name] = value
                return response
        response = await call_next(request)
        for name, value in _SECURITY_HEADERS.items():
            response.headers[name] = value
        return response

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> JSONResponse:
        return _json({"status": "ok"})

    @app.get("/robots.txt", include_in_schema=False)
    def robots() -> PlainTextResponse:
        return PlainTextResponse(
            "User-agent: *\nDisallow: /\n", headers={"Cache-Control": "no-store"}
        )

    @app.get("/login", include_in_schema=False)
    def login_form(request: Request) -> HTMLResponse:
        if (
            password is not None
            and session_secret is not None
            and _valid_session(request.cookies.get(_SESSION_COOKIE), session_secret)
        ):
            return HTMLResponse(status_code=HTTPStatus.SEE_OTHER, headers={"Location": "/"})
        return _login_page(next_path=request.query_params.get("next", "/"))

    @app.post("/login", include_in_schema=False)
    async def login(request: Request) -> HTMLResponse:
        if password is None:
            return HTMLResponse(status_code=HTTPStatus.SEE_OTHER, headers={"Location": "/"})
        body = await request.body()
        form = parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)
        supplied = form.get("password", [""])[0]
        next_path = form.get("next", ["/"])[0]
        if not _password_matches(supplied, password):
            return _login_page(invalid=True, next_path=next_path)
        assert session_secret is not None
        response = HTMLResponse(
            status_code=HTTPStatus.SEE_OTHER,
            headers={"Location": _safe_next(next_path)},
        )
        response.set_cookie(
            _SESSION_COOKIE,
            _session_token(session_secret),
            max_age=_SESSION_SECONDS,
            httponly=True,
            secure=secure_cookie,
            samesite="strict",
            path="/",
        )
        return response

    @app.post("/logout", include_in_schema=False)
    def logout() -> HTMLResponse:
        response = HTMLResponse(
            status_code=HTTPStatus.SEE_OTHER,
            headers={"Location": "/login", "Cache-Control": "no-store"},
        )
        response.delete_cookie(
            _SESSION_COOKIE,
            path="/",
            httponly=True,
            secure=secure_cookie,
            samesite="strict",
        )
        return response

    @app.api_route("/api/datasets", methods=["GET", "HEAD"])
    def datasets() -> JSONResponse:
        return _api_call(lambda: list_datasets(path))

    @app.api_route("/api/people/search", methods=["GET", "HEAD"])
    def people_search(request: Request) -> JSONResponse:
        parameters = _parameters(request)
        dataset = _first(parameters, "dataset", "dataset_id")
        query = _first(parameters, "q", "query")
        if dataset is None or query is None:
            return _json(
                {"error": "dataset and q query parameters are required"},
                HTTPStatus.BAD_REQUEST,
            )
        return _api_call(
            lambda: search_people(
                path,
                _identifier(dataset),
                query,
                limit=int(_first(parameters, "limit") or "50"),
            )
        )

    @app.api_route("/api/people", methods=["GET", "HEAD"])
    def people(request: Request) -> JSONResponse:
        parameters = _parameters(request)
        dataset = _first(parameters, "dataset", "dataset_id")
        if dataset is None:
            return _json({"error": "dataset query parameter is required"}, HTTPStatus.BAD_REQUEST)
        return _api_call(
            lambda: list_people(
                path,
                _identifier(dataset),
                limit=int(_first(parameters, "limit") or "100"),
                offset=int(_first(parameters, "offset") or "0"),
            )
        )

    @app.api_route("/api/relationship", methods=["GET", "HEAD"])
    def relationship(request: Request) -> JSONResponse:
        parameters = _parameters(request)
        dataset = _first(parameters, "dataset", "dataset_id")
        source = _first(parameters, "from", "from_id", "from_person_id", "person1", "person_a")
        target = _first(parameters, "to", "to_id", "to_person_id", "person2", "person_b")
        if dataset is None or source is None or target is None:
            return _json(
                {"error": "dataset, from, and to query parameters are required"},
                HTTPStatus.BAD_REQUEST,
            )
        return _api_call(
            lambda: shortest_relationship_path(
                path, _identifier(dataset), _identifier(source), _identifier(target)
            )
        )

    def person_response(
        request: Request,
        dataset_text: str,
        person_text: str,
        action: str | None,
    ) -> JSONResponse:
        if action not in {None, "family", "facts", "tree"}:
            return _json({"error": "API endpoint not found"}, HTTPStatus.NOT_FOUND)
        parameters = _parameters(request)
        dataset_id = _identifier(dataset_text)
        person_id = _identifier(person_text)

        def query() -> Any:
            if action == "family":
                return get_family(path, dataset_id, person_id)
            if action == "facts":
                return get_person_facts(path, dataset_id, person_id)
            if action == "tree":
                return get_tree(
                    path,
                    dataset_id,
                    person_id,
                    direction=_first(parameters, "direction") or "ancestors",
                    max_depth=int(_first(parameters, "max_depth", "generations") or "4"),
                )
            return get_person(path, dataset_id, person_id)

        return _api_call(query, missing_person=True)

    @app.api_route("/api/people/{dataset_text}/{person_text}", methods=["GET", "HEAD"])
    def person(request: Request, dataset_text: str, person_text: str) -> JSONResponse:
        return person_response(request, dataset_text, person_text, None)

    @app.api_route("/api/people/{dataset_text}/{person_text}/{action}", methods=["GET", "HEAD"])
    def person_action(
        request: Request, dataset_text: str, person_text: str, action: str
    ) -> JSONResponse:
        return person_response(request, dataset_text, person_text, action)

    @app.api_route("/api/{api_path:path}", methods=["GET", "HEAD"])
    def unknown_api(api_path: str) -> JSONResponse:
        del api_path
        return _json({"error": "API endpoint not found"}, HTTPStatus.NOT_FOUND)

    def static_file(relative_path: str) -> FileResponse | JSONResponse:
        try:
            relative = PurePosixPath(relative_path)
            if (
                not relative.parts
                or "\x00" in relative_path
                or "\\" in relative_path
                or any(part in {"", ".", ".."} for part in relative.parts)
            ):
                raise ValueError
            candidate = static_root.joinpath(*relative.parts).resolve()
            candidate.relative_to(static_root)
        except (OSError, ValueError):
            return _json({"detail": "Not Found"}, HTTPStatus.NOT_FOUND)
        if not candidate.is_file():
            return _json({"detail": "Not Found"}, HTTPStatus.NOT_FOUND)
        return FileResponse(candidate)

    @app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(static_root / "index.html")

    @app.api_route(
        "/dataset/{dataset}/person/{person_id}", methods=["GET", "HEAD"], include_in_schema=False
    )
    def person_page(dataset: str, person_id: str) -> FileResponse:
        del dataset, person_id
        return FileResponse(static_root / "index.html")

    @app.api_route("/data/{data_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def unavailable_data(data_path: str) -> JSONResponse:
        del data_path
        return _json({"detail": "Not Found"}, HTTPStatus.NOT_FOUND)

    @app.api_route("/{asset_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def assets(asset_path: str) -> Response:
        return static_file(asset_path)

    return app


def serve(
    database_path: str | PathLike[str],
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> None:
    """Serve package static assets and JSON APIs until interrupted."""

    app = create_app(
        database_path,
        password=os.getenv("FAMILY_PASSWORD") or None,
        session_secret=os.getenv("SESSION_SECRET") or None,
        secure_cookie=os.getenv("SESSION_COOKIE_SECURE") == "1",
    )
    browser_host = host if host not in {"", "0.0.0.0", "::"} else "127.0.0.1"
    if ":" in browser_host and not browser_host.startswith("["):
        browser_host = f"[{browser_host}]"
    url = f"http://{browser_host}:{port}/"
    if open_browser:
        timer = threading.Timer(0.1, webbrowser.open, args=(url,))
        timer.daemon = True
        timer.start()
    print(f"Serving Legacy Family Tree browser at {url}")
    uvicorn.run(app, host=host, port=port)


__all__ = ["create_app", "serve"]
