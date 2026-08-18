"""Command-line interface for Legacy Family Tree Reader."""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from .build_tools import BuildError, build_mdbtools
from .exporters import export_excel, export_gedcom
from .identity import IdentityError, link_people, suggest_links
from .importer import ImportError as LegacyImportError
from .importer import import_database, raw_mdb_to_sqlite
from .queries import (
    get_ancestors,
    get_descendants,
    get_family,
    get_person,
    get_person_facts,
    list_datasets,
    search_people,
    shortest_relationship_path,
)
from .schema import LEGACY_SCHEMA_VERSION, SCHEMA_VERSION, TABLES
from .server import serve


def _identifier(value: str) -> int | str:
    try:
        return int(value)
    except ValueError:
        return value


def _json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def _add_person_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("database", metavar="DB")
    parser.add_argument("dataset", type=_identifier, metavar="DATASET")
    parser.add_argument("person_id", type=_identifier, metavar="PERSON_ID")


def _query_command(function: Callable[..., Any], *, depth: bool = False) -> Callable[[Any], int]:
    def run(arguments: argparse.Namespace) -> int:
        keywords = {"max_depth": arguments.depth} if depth else {}
        result = function(arguments.database, arguments.dataset, arguments.person_id, **keywords)
        if result is None:
            _json({"error": "person not found"})
            return 1
        _json(result)
        return 0

    return run


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="legacy-family-tree",
        description="Convert, merge, browse, query, and export Legacy Family Tree data.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    import_parser = subparsers.add_parser("import", help="import one source into a database")
    import_parser.add_argument("source", metavar="SOURCE")
    import_parser.add_argument("output", metavar="OUTPUT")
    import_parser.add_argument("--name", help="dataset name (defaults to the source stem)")
    import_parser.add_argument("--allow-duplicate", action="store_true")
    import_parser.set_defaults(handler=_cmd_import)

    merge_parser = subparsers.add_parser("merge", help="import several datasets into one database")
    merge_parser.add_argument("output", metavar="OUTPUT")
    merge_parser.add_argument("sources", nargs="+", metavar="SOURCE")
    merge_parser.add_argument(
        "--name",
        action="append",
        dest="names",
        metavar="NAME",
        help="dataset name in source order; repeat once per source",
    )
    merge_parser.add_argument("--allow-duplicate", action="store_true")
    merge_parser.set_defaults(handler=_cmd_merge)

    raw_parser = subparsers.add_parser(
        "mdb2sqlite", help="create a raw tbl* compatibility database"
    )
    _add_raw_arguments(raw_parser)
    raw_parser.set_defaults(handler=_cmd_raw)

    browse_parser = subparsers.add_parser("browse", help="run the local read-only web browser")
    browse_parser.add_argument("database", metavar="DB")
    browse_parser.add_argument("--host", default="127.0.0.1")
    browse_parser.add_argument("--port", type=int, default=8765)
    browse_parser.add_argument("--no-browser", action="store_true")
    browse_parser.set_defaults(handler=_cmd_browse)

    search_parser = subparsers.add_parser("search", help="search people by name")
    search_parser.add_argument("database", metavar="DB")
    search_parser.add_argument("dataset", type=_identifier, metavar="DATASET")
    search_parser.add_argument("query", metavar="QUERY")
    search_parser.add_argument("--limit", type=int, default=50)
    search_parser.set_defaults(handler=_cmd_search)

    for name, help_text, function in (
        ("person", "show a person", get_person),
        ("family", "show immediate family", get_family),
        ("facts", "show all attached person facts", get_person_facts),
    ):
        query_parser = subparsers.add_parser(name, help=help_text)
        _add_person_arguments(query_parser)
        query_parser.set_defaults(handler=_query_command(function))

    for name, function in (
        ("ancestors", get_ancestors),
        ("descendants", get_descendants),
    ):
        tree_parser = subparsers.add_parser(name, help=f"show a person's {name}")
        _add_person_arguments(tree_parser)
        tree_parser.add_argument("--depth", type=int, default=4, metavar="GENERATIONS")
        tree_parser.set_defaults(handler=_query_command(function, depth=True))

    related_parser = subparsers.add_parser("related", help="find a shortest relationship path")
    related_parser.add_argument("database", metavar="DB")
    related_parser.add_argument("dataset", type=_identifier, metavar="DATASET")
    related_parser.add_argument("person_a", type=_identifier, metavar="PERSON_A")
    related_parser.add_argument("person_b", type=_identifier, metavar="PERSON_B")
    related_parser.set_defaults(handler=_cmd_related)

    for command, help_text, handler in (
        ("export-gedcom", "export GEDCOM 5.5.1", _cmd_export_gedcom),
        ("export-excel", "export an Excel workbook", _cmd_export_excel),
    ):
        export_parser = subparsers.add_parser(command, help=help_text)
        export_parser.add_argument("database", metavar="DB")
        export_parser.add_argument("output", metavar="OUTPUT")
        export_parser.add_argument("dataset", nargs="?", type=_identifier, metavar="DATASET")
        export_parser.add_argument(
            "--exclude-private",
            action="store_true",
            help="omit records marked private or living",
        )
        export_parser.set_defaults(handler=handler)

    datasets_parser = subparsers.add_parser("datasets", help="list imported datasets")
    datasets_parser.add_argument("database", metavar="DB")
    datasets_parser.set_defaults(handler=_cmd_datasets)

    schema_parser = subparsers.add_parser("schema", help="print the supported Legacy schema")
    schema_parser.set_defaults(handler=_cmd_schema)

    link_parser = subparsers.add_parser(
        "link-person", help="explicitly link people across datasets"
    )
    link_parser.add_argument("database", metavar="DB")
    link_parser.add_argument("dataset_a", type=int, metavar="DATASET_A")
    link_parser.add_argument("person_a", type=int, metavar="PERSON_A")
    link_parser.add_argument("dataset_b", type=int, metavar="DATASET_B")
    link_parser.add_argument("person_b", type=int, metavar="PERSON_B")
    link_parser.set_defaults(handler=_cmd_link_person)

    suggest_parser = subparsers.add_parser(
        "suggest-links", help="suggest conservative cross-dataset identity matches"
    )
    suggest_parser.add_argument("database", metavar="DB")
    suggest_parser.add_argument("datasets", nargs="*", type=int, metavar="DATASET")
    suggest_parser.add_argument("--limit", type=int, default=100)
    suggest_parser.set_defaults(handler=_cmd_suggest_links)

    build_parser = subparsers.add_parser(
        "build-mdbtools", help="build and install mdbtools with LLVM"
    )
    build_parser.add_argument("--ref", default="dev")
    build_parser.add_argument("--source-dir")
    build_parser.add_argument("--build-dir")
    build_parser.add_argument("--prefix")
    build_parser.add_argument("--jobs", type=int)
    build_parser.add_argument("--dry-run", action="store_true")
    build_parser.set_defaults(handler=_cmd_build_mdbtools)
    return parser


def _add_raw_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("output", metavar="OUTPUT")
    parser.add_argument("sources", nargs="+", metavar="SOURCE")


def _cmd_import(arguments: argparse.Namespace) -> int:
    dataset_id = import_database(
        arguments.source,
        arguments.output,
        dataset_name=arguments.name,
        allow_duplicate=arguments.allow_duplicate,
    )
    _json({"dataset_id": dataset_id, "output": str(Path(arguments.output))})
    return 0


def _cmd_merge(arguments: argparse.Namespace) -> int:
    names = arguments.names or [None] * len(arguments.sources)
    if len(names) != len(arguments.sources):
        raise ValueError("--name must be omitted or repeated once for each source")
    imported = []
    for source, name in zip(arguments.sources, names, strict=True):
        dataset_id = import_database(
            source,
            arguments.output,
            dataset_name=name,
            allow_duplicate=arguments.allow_duplicate,
        )
        imported.append({"dataset_id": dataset_id, "source": source, "name": name})
    _json({"output": str(Path(arguments.output)), "datasets": imported})
    return 0


_ACCESS_SUFFIXES = {".fdb", ".mdb", ".accdb", ".hdb"}
_OUTPUT_SUFFIXES = {".db", ".sqlite", ".sqlite3"}


def _looks_like_old_raw_order(output: str, sources: Sequence[str]) -> bool:
    if len(sources) != 2:
        return False
    return (
        Path(output).suffix.casefold() in _ACCESS_SUFFIXES
        and Path(sources[0]).suffix.casefold() in _ACCESS_SUFFIXES
        and Path(sources[1]).suffix.casefold() in _OUTPUT_SUFFIXES
    )


def _cmd_raw(arguments: argparse.Namespace) -> int:
    if _looks_like_old_raw_order(arguments.output, arguments.sources):
        raise ValueError(
            "old FDB HDB OUTPUT argument order detected; use OUTPUT SOURCE... "
            "so no source file can be opened as the output"
        )
    raw_mdb_to_sqlite(arguments.sources, arguments.output)
    _json({"output": str(Path(arguments.output)), "sources": arguments.sources})
    return 0


def _cmd_browse(arguments: argparse.Namespace) -> int:
    if not 0 <= arguments.port <= 65535:
        raise ValueError("port must be between 0 and 65535")
    serve(
        arguments.database,
        host=arguments.host,
        port=arguments.port,
        open_browser=not arguments.no_browser,
    )
    return 0


def _cmd_search(arguments: argparse.Namespace) -> int:
    _json(
        search_people(
            arguments.database,
            arguments.dataset,
            arguments.query,
            limit=arguments.limit,
        )
    )
    return 0


def _cmd_related(arguments: argparse.Namespace) -> int:
    _json(
        shortest_relationship_path(
            arguments.database,
            arguments.dataset,
            arguments.person_a,
            arguments.person_b,
        )
    )
    return 0


def _cmd_export_gedcom(arguments: argparse.Namespace) -> int:
    export_gedcom(
        arguments.database,
        arguments.output,
        arguments.dataset,
        include_private=not arguments.exclude_private,
    )
    _json({"output": str(Path(arguments.output)), "format": "gedcom"})
    return 0


def _cmd_export_excel(arguments: argparse.Namespace) -> int:
    export_excel(
        arguments.database,
        arguments.output,
        arguments.dataset,
        include_private=not arguments.exclude_private,
    )
    _json({"output": str(Path(arguments.output)), "format": "excel"})
    return 0


def _cmd_datasets(arguments: argparse.Namespace) -> int:
    _json(list_datasets(arguments.database))
    return 0


def _cmd_schema(_arguments: argparse.Namespace) -> int:
    _json(
        {
            "schema_version": SCHEMA_VERSION,
            "legacy_version": LEGACY_SCHEMA_VERSION,
            "tables": [
                {
                    "source_table": table.source_name,
                    "table": table.name,
                    "description": table.description,
                    "columns": [
                        {
                            "source_column": column.source_name,
                            "column": column.name,
                            "storage_type": column.storage_type,
                            "description": column.description,
                        }
                        for column in table.columns
                    ],
                }
                for table in TABLES
            ],
        }
    )
    return 0


def _cmd_link_person(arguments: argparse.Namespace) -> int:
    _json(
        link_people(
            arguments.database,
            arguments.dataset_a,
            arguments.person_a,
            arguments.dataset_b,
            arguments.person_b,
        )
    )
    return 0


def _cmd_suggest_links(arguments: argparse.Namespace) -> int:
    if len(arguments.datasets) > 2:
        raise ValueError("specify at most two datasets")
    _json(
        suggest_links(
            arguments.database,
            arguments.datasets or None,
            limit=arguments.limit,
        )
    )
    return 0


def _cmd_build_mdbtools(arguments: argparse.Namespace) -> int:
    keywords: dict[str, Any] = {
        "ref": arguments.ref,
        "jobs": arguments.jobs,
        "dry_run": arguments.dry_run,
    }
    for argument, parameter in (
        (arguments.source_dir, "source_dir"),
        (arguments.build_dir, "build_dir"),
        (arguments.prefix, "prefix"),
    ):
        if argument is not None:
            keywords[parameter] = argument
    build_mdbtools(**keywords)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    arguments = parser.parse_args(argv)
    try:
        return int(arguments.handler(arguments))
    except KeyboardInterrupt:
        print("legacy-family-tree: interrupted", file=sys.stderr)
        return 130
    except (
        BuildError,
        IdentityError,
        LegacyImportError,
        FileNotFoundError,
        OSError,
        sqlite3.Error,
        subprocess.CalledProcessError,
        ValueError,
    ) as error:
        print(f"legacy-family-tree: error: {error}", file=sys.stderr)
        return 1


def mdb2sqlite_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mdb2sqlite",
        description="Convert FDB/MDB sources to a raw tbl* SQLite database.",
    )
    _add_raw_arguments(parser)
    arguments = parser.parse_args(argv)
    try:
        return _cmd_raw(arguments)
    except (LegacyImportError, FileNotFoundError, OSError, sqlite3.Error, ValueError) as error:
        print(f"mdb2sqlite: error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
