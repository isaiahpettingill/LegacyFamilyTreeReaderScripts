from __future__ import annotations

import io
import sqlite3
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

from legacy_family_tree_reader import build_tools, cli, importer


class _FakePopen:
    def __init__(self, command: list[str], **_kwargs: object) -> None:
        self.command = command
        table = command[-1]
        csv_by_table = {
            "tblHR": "Item,Setting\nLegacyVer,9.0\n",
            "tblIR": "ID,IDIR,GivenName,Surname,Gender\n1,1,Mock,Person,0\n",
        }
        self.stdout = io.StringIO(csv_by_table[table])
        self.stderr = io.StringIO("")
        self.returncode = 0

    def poll(self) -> int:
        return self.returncode

    def wait(self) -> int:
        return self.returncode

    def terminate(self) -> None:
        self.returncode = -15


def test_raw_mdb_to_sqlite_mocks_mdbtools_subprocesses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "synthetic.fdb"
    source.write_bytes(b"not a real Access database")
    output = tmp_path / "raw.sqlite"
    run_commands: list[list[str]] = []
    popen_commands: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        run_commands.append(command)
        return SimpleNamespace(returncode=0, stdout="tblHR\ntblIR\n", stderr="")

    def fake_popen(command: list[str], **kwargs: object) -> _FakePopen:
        popen_commands.append(command)
        return _FakePopen(command, **kwargs)

    monkeypatch.setattr(importer.shutil, "which", lambda command: f"/mock/bin/{command}")
    monkeypatch.setattr(importer.subprocess, "run", fake_run)
    monkeypatch.setattr(importer.subprocess, "Popen", fake_popen)

    importer.raw_mdb_to_sqlite(source, output)

    assert run_commands == [["/mock/bin/mdb-tables", "-1", str(source.resolve())]]
    assert [command[-1] for command in popen_commands] == ["tblHR", "tblIR"]
    assert all(command[1:3] == ["-0", importer._NULL_MARKER] for command in popen_commands)
    with sqlite3.connect(output) as connection:
        assert connection.execute("SELECT IDIR, GivenName, Gender FROM tblIR").fetchone() == (
            1,
            "Mock",
            0,
        )
        assert connection.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name LIKE 'tbl%'"
        ).fetchone() == (38,)


def test_cli_argument_safety_and_old_mdb2sqlite_order_diagnostic(
    tmp_path: Path,
    raw_factory: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = raw_factory(marker="same-path")
    original = source.read_bytes()
    assert cli.main(["import", str(source), str(source)]) == 1
    assert source.read_bytes() == original
    assert "source and output database paths must differ" in capsys.readouterr().err

    called = False

    def fail_if_called(*_args: object, **_kwargs: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(cli, "raw_mdb_to_sqlite", fail_if_called)
    result = cli.mdb2sqlite_main(["family.fdb", "archive.hdb", "result.sqlite"])
    assert result == 1
    assert called is False
    assert "old FDB HDB OUTPUT argument order detected" in capsys.readouterr().err

    parsed = cli._build_parser().parse_args(
        ["mdb2sqlite", "safe.sqlite", "--", "-leading-name.fdb"]
    )
    assert parsed.output == "safe.sqlite"
    assert parsed.sources == ["-leading-name.fdb"]


def test_llvm_build_dry_run_checks_tools_but_executes_no_build_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    subprocess_calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        subprocess_calls.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(build_tools.shutil, "which", lambda command: f"/mock/bin/{command}")
    monkeypatch.setattr(build_tools.subprocess, "run", fake_run)
    source = tmp_path / "mdbtools-source"
    build = tmp_path / "llvm-build"
    prefix = tmp_path / "install prefix"

    build_tools.build_mdbtools(
        ref="v1.2.3",
        source_dir=source,
        build_dir=build,
        prefix=prefix,
        jobs=3,
        dry_run=True,
    )

    assert subprocess_calls == [["pkg-config", "--exists", "glib-2.0"]]
    output = capsys.readouterr().out
    assert "git clone https://github.com/mdbtools/mdbtools" in output
    assert "git checkout --detach v1.2.3" in output
    assert "autoreconf -fi" in output
    assert f"--prefix={prefix.resolve()}" in output
    assert "make -j3" in output
    assert "make install" in output
    assert not source.exists()
    assert not build.exists()


def test_cli_forwards_llvm_dry_run_options(monkeypatch: pytest.MonkeyPatch) -> None:
    received: dict[str, object] = {}
    monkeypatch.setattr(cli, "build_mdbtools", lambda **kwargs: received.update(kwargs))
    assert (
        cli.main(
            [
                "build-mdbtools",
                "--ref",
                "release",
                "--source-dir",
                "source",
                "--build-dir",
                "build",
                "--prefix",
                "prefix",
                "--jobs",
                "2",
                "--dry-run",
            ]
        )
        == 0
    )
    assert received == {
        "ref": "release",
        "jobs": 2,
        "dry_run": True,
        "source_dir": "source",
        "build_dir": "build",
        "prefix": "prefix",
    }
