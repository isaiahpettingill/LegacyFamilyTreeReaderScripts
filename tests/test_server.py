from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from legacy_family_tree_reader.queries import connect_read_only
from legacy_family_tree_reader.server import create_app


def test_api_contract_and_error_mappings(merged_db: Path) -> None:
    with TestClient(create_app(merged_db)) as client:
        datasets = client.get("/api/datasets")
        assert datasets.status_code == 200
        assert datasets.headers["Cache-Control"] == "no-store"
        assert len(datasets.json()) == 2

        search = client.get(
            "/api/people/search", params={"dataset_id": 1, "query": "harbor morgan"}
        )
        assert [person["person_id"] for person in search.json()] == [3]

        page = client.get("/api/people", params={"dataset": 1, "limit": 2, "offset": 2}).json()
        assert page["total"] == 6
        assert len(page["people"]) == 2
        assert page["offset"] == 2

        person = client.get("/api/people/1/3")
        facts = client.get("/api/people/1/3/facts")
        family = client.get("/api/people/1/3/family")
        tree = client.get(
            "/api/people/1/3/tree", params={"direction": "ancestors", "generations": 2}
        )
        relationship = client.get(
            "/api/relationship", params={"dataset": 1, "person_a": 1, "person_b": 5}
        )
        assert person.json()["person_id"] == 3
        assert client.get("/api/people/1/3", params={"action": "ignored"}).json()["person_id"] == 3
        assert facts.json()["person"]["person_id"] == 3
        assert family.json()["person"]["person_id"] == 3
        assert tree.json()["root"]["person_id"] == 3
        assert relationship.json()["found"] is True

        missing_parameter = client.get("/api/people/search", params={"q": "Morgan"})
        assert missing_parameter.status_code == 400
        assert missing_parameter.json() == {"error": "dataset and q query parameters are required"}
        invalid_number = client.get("/api/people", params={"dataset": 1, "limit": "many"})
        assert invalid_number.status_code == 400
        assert "invalid literal" in invalid_number.json()["error"]
        assert client.get("/api/people/1/999").json() == {"error": "Person not found"}
        assert client.get("/api/people/1/999").status_code == 404
        unknown = client.get("/api/not-an-endpoint")
        assert unknown.status_code == 404
        assert unknown.json() == {"error": "API endpoint not found"}


def test_packaged_assets_deep_route_and_data_are_separated(merged_db: Path) -> None:
    with TestClient(create_app(merged_db)) as client:
        index = client.get("/")
        deep_route = client.get("/dataset/1/person/3")
        full_tree_route = client.get("/full-tree")
        asset = client.get("/app.js")

        assert index.status_code == deep_route.status_code == full_tree_route.status_code == 200
        assert deep_route.content == index.content
        assert full_tree_route.content == index.content
        assert index.headers["Cache-Control"] == "no-cache"
        assert asset.headers["Cache-Control"] == "no-cache"
        assert "Legacy Family Archive" in index.text
        assert "app.js?v=0.6.0" in index.text
        assert '<script src="vendor/sql-asm.js"' not in index.text
        assert '<script src="standalone.js"' not in index.text
        assert "javascript" in asset.headers["Content-Type"]

        assert client.get("/data/manifest.json").status_code == 404
        assert client.get("/data/family-tree.sqlite.part000").status_code == 404
        assert client.get("/%2e%2e/secret.txt").status_code == 404
        assert client.get("/missing.txt").status_code == 404


def test_password_login_cookie_and_logout_work_without_origin_header(merged_db: Path) -> None:
    with TestClient(
        create_app(merged_db, password="family password", session_secret="test-session-secret")
    ) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        robots = client.get("/robots.txt")
        assert robots.status_code == 200
        assert "Disallow: /" in robots.text

        api = client.get("/api/datasets")
        assert api.status_code == 401
        assert api.json() == {"error": "Authentication required"}
        asset = client.get("/app.js", follow_redirects=False)
        assert asset.status_code == 303
        assert asset.headers["Location"] == "/login?next=%2Fapp.js"
        assert client.get("/login").status_code == 200

        deep_route = client.get("/dataset/1/person/3?view=tree", follow_redirects=False)
        assert deep_route.status_code == 303
        assert deep_route.headers["Location"] == (
            "/login?next=%2Fdataset%2F1%2Fperson%2F3%3Fview%3Dtree"
        )

        login = client.post(
            "/login",
            data={
                "password": "family password",
                "next": "/dataset/1/person/3?view=tree",
            },
            follow_redirects=False,
        )
        assert login.status_code == 303
        assert login.headers["Location"] == "/dataset/1/person/3?view=tree"
        cookie = login.headers["Set-Cookie"]
        assert "family_session=" in cookie
        assert "Max-Age=43200" in cookie
        assert "HttpOnly" in cookie
        assert "SameSite=strict" in cookie
        assert client.get("/api/datasets").status_code == 200
        assert client.get("/app.js").status_code == 200

        logout = client.post("/logout", follow_redirects=False)
        assert logout.status_code == 303
        assert logout.headers["Location"] == "/login"
        assert "family_session=" in logout.headers["Set-Cookie"]
        assert client.get("/api/datasets").status_code == 401


def test_wrong_password_and_tampered_cookie_are_rejected(merged_db: Path) -> None:
    with TestClient(create_app(merged_db, password="correct", session_secret="secret")) as client:
        wrong = client.post("/login", data={"password": "incorrect"})
        assert wrong.status_code == 401
        assert "Invalid password" in wrong.text
        assert "family_session" not in wrong.cookies

        client.cookies.set("family_session", "9999999999.not-a-valid-signature")
        assert client.get("/api/datasets").status_code == 401


def test_production_session_cookie_is_secure(merged_db: Path) -> None:
    with TestClient(
        create_app(
            merged_db,
            password="correct",
            session_secret="secret",
            secure_cookie=True,
        )
    ) as client:
        login = client.post(
            "/login",
            data={"password": "correct", "next": "//attacker.example/path"},
            follow_redirects=False,
        )
        assert login.status_code == 303
        assert login.headers["Location"] == "/"
        assert "Secure" in login.headers["Set-Cookie"]


@pytest.mark.parametrize("path", ["/", "/api/datasets", "/healthz", "/robots.txt"])
def test_security_headers_deny_embedding_and_indexing(merged_db: Path, path: str) -> None:
    with TestClient(create_app(merged_db)) as client:
        response = client.get(path)
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["Referrer-Policy"] == "no-referrer"
        assert response.headers["X-Robots-Tag"] == "noindex, nofollow, noarchive"
        assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
        assert "unsafe-eval" not in response.headers["Content-Security-Policy"]


def test_database_is_validated_read_only_during_startup(tmp_path: Path, merged_db: Path) -> None:
    invalid = tmp_path / "not-sqlite.db"
    invalid.write_text("not sqlite", encoding="ascii")
    with pytest.raises(sqlite3.DatabaseError), TestClient(create_app(invalid)):
        pass

    connection = connect_read_only(merged_db)
    try:
        assert connection.execute("PRAGMA query_only").fetchone() == (1,)
        with pytest.raises(sqlite3.OperationalError, match="readonly|read-only"):
            connection.execute("DELETE FROM datasets")
    finally:
        connection.close()


def test_password_requires_a_session_secret(merged_db: Path) -> None:
    with pytest.raises(ValueError, match="session_secret"):
        create_app(merged_db, password="configured")


def test_database_failures_keep_the_existing_json_mapping(
    monkeypatch: pytest.MonkeyPatch, merged_db: Path
) -> None:
    from legacy_family_tree_reader import server

    def fail(_database: Path) -> None:
        raise sqlite3.OperationalError("synthetic failure")

    monkeypatch.setattr(server, "list_datasets", fail)
    with TestClient(create_app(merged_db)) as client:
        response = client.get("/api/datasets")
    assert response.status_code == 500
    assert response.json() == {
        "error": "Database query failed",
        "detail": "synthetic failure",
    }


def test_serve_uses_environment_uvicorn_and_browser_timer(
    monkeypatch: pytest.MonkeyPatch, merged_db: Path
) -> None:
    from legacy_family_tree_reader import server

    calls: dict[str, object] = {}
    sentinel_app = object()

    def fake_create_app(
        database: str | Path,
        password: str | None = None,
        session_secret: str | None = None,
        secure_cookie: bool = False,
    ) -> object:
        calls["create"] = (database, password, session_secret, secure_cookie)
        return sentinel_app

    class FakeTimer:
        daemon = False

        def __init__(self, interval: float, function: object, args: tuple[str]) -> None:
            calls["timer"] = (interval, function, args)

        def start(self) -> None:
            calls["timer_started"] = True
            calls["timer_daemon"] = self.daemon

    def fake_run(app: object, *, host: str, port: int) -> None:
        calls["uvicorn"] = (app, host, port)

    monkeypatch.setenv("FAMILY_PASSWORD", "environment-password")
    monkeypatch.setenv("SESSION_SECRET", "environment-secret")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "1")
    monkeypatch.setattr(server, "create_app", fake_create_app)
    monkeypatch.setattr(server.threading, "Timer", FakeTimer)
    monkeypatch.setattr(server.uvicorn, "run", fake_run)

    server.serve(merged_db, host="0.0.0.0", port=4321)

    assert calls["create"] == (merged_db, "environment-password", "environment-secret", True)
    assert calls["uvicorn"] == (sentinel_app, "0.0.0.0", 4321)
    assert calls["timer_started"] is True
    assert calls["timer_daemon"] is True
    assert calls["timer"][2] == ("http://127.0.0.1:4321/",)  # type: ignore[index]


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
