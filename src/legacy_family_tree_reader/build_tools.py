"""Build the mdbtools command-line utilities with LLVM."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

MDBTOOLS_REPOSITORY = "https://github.com/mdbtools/mdbtools"


class BuildError(RuntimeError):
    """Raised when mdbtools cannot be configured or built."""


def _display(command: Sequence[str]) -> str:
    return " ".join(
        repr(part) if any(char.isspace() for char in part) else part for part in command
    )


def _run(
    command: Sequence[str],
    *,
    cwd: Path | None,
    env: dict[str, str],
    dry_run: bool,
) -> None:
    location = f" (in {cwd})" if cwd else ""
    print(f"+ {_display(command)}{location}")
    if not dry_run:
        subprocess.run(list(command), cwd=cwd, env=env, check=True)


def _check_dependencies() -> None:
    required = (
        "git",
        "autoreconf",
        "autoconf",
        "automake",
        "libtoolize",
        "make",
        "clang",
        "clang++",
        "pkg-config",
    )
    missing = [command for command in required if shutil.which(command) is None]
    if missing:
        raise BuildError(
            "missing build commands: "
            + ", ".join(missing)
            + ". Install LLVM/Clang, git, make, autoconf, automake, and libtool; "
            "mdbtools also requires the GLib development headers and pkg-config."
        )
    if subprocess.run(
        ["pkg-config", "--exists", "glib-2.0"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode:
        raise BuildError(
            "GLib development files were not found by pkg-config; install the "
            "glib2 development package for your operating system"
        )


def build_mdbtools(
    *,
    ref: str = "dev",
    source_dir: str | Path | None = None,
    build_dir: str | Path | None = None,
    prefix: str | Path | None = None,
    jobs: int | None = None,
    dry_run: bool = False,
) -> None:
    """Clone or update, configure, build, and install mdbtools using Clang."""

    _check_dependencies()
    source = (
        Path(
            source_dir
            if source_dir is not None
            else Path.home() / ".cache/legacy-family-tree-reader/mdbtools"
        )
        .expanduser()
        .resolve()
    )
    build = (
        Path(build_dir).expanduser().resolve() if build_dir is not None else source / "build-llvm"
    )
    install_prefix = Path(prefix if prefix is not None else Path.home() / ".local")
    install_prefix = install_prefix.expanduser().resolve()
    job_count = jobs if jobs is not None else (os.cpu_count() or 1)
    if job_count < 1:
        raise ValueError("jobs must be at least 1")
    git_directory = source / ".git"
    if build == source or build == git_directory or git_directory in build.parents:
        raise ValueError("build directory must not be the source or its .git directory")

    env = os.environ.copy()
    env.update({"CC": "clang", "CXX": "clang++"})
    if source.exists():
        if not (source / ".git").is_dir():
            raise BuildError(f"source directory exists but is not a git checkout: {source}")
        _run(["git", "fetch", "--tags", "origin"], cwd=source, env=env, dry_run=dry_run)
        remote_ref = f"refs/remotes/origin/{ref}^{{commit}}"
        use_remote = False
        if not dry_run:
            use_remote = (
                subprocess.run(
                    ["git", "rev-parse", "--verify", "--quiet", remote_ref],
                    cwd=source,
                    env=env,
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                ).returncode
                == 0
            )
        checkout_ref = f"origin/{ref}" if use_remote else ref
        _run(
            ["git", "checkout", "--detach", checkout_ref],
            cwd=source,
            env=env,
            dry_run=dry_run,
        )
    else:
        if not dry_run:
            source.parent.mkdir(parents=True, exist_ok=True)
        _run(
            ["git", "clone", MDBTOOLS_REPOSITORY, str(source)],
            cwd=None,
            env=env,
            dry_run=dry_run,
        )
        _run(
            ["git", "checkout", "--detach", ref],
            cwd=source,
            env=env,
            dry_run=dry_run,
        )

    if not dry_run:
        build.mkdir(parents=True, exist_ok=True)
    _run(["autoreconf", "-fi"], cwd=source, env=env, dry_run=dry_run)
    _run(
        [str(source / "configure"), f"--prefix={install_prefix}"],
        cwd=build,
        env=env,
        dry_run=dry_run,
    )
    _run(["make", f"-j{job_count}"], cwd=build, env=env, dry_run=dry_run)
    _run(["make", "install"], cwd=build, env=env, dry_run=dry_run)


__all__ = ["MDBTOOLS_REPOSITORY", "BuildError", "build_mdbtools"]
