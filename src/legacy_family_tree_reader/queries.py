"""Read-only queries for the descriptive Legacy Family Tree SQLite database."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from itertools import pairwise
from os import PathLike
from pathlib import Path
from typing import Any, TypeAlias

from .dates import decode_legacy_date

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]
DatabaseSource: TypeAlias = sqlite3.Connection | str | PathLike[str]

_PERSON_NAME_COLUMNS = ("title_prefix", "given_names", "surname", "title_suffix")
_IDENTITY_COLUMNS = (
    "dataset_id",
    "person_id",
    "legacy_rin",
    "title_prefix",
    "given_names",
    "surname",
    "title_suffix",
    "gender_code",
    "birth_legacy_date",
    "birth_sort_date_key",
    "death_legacy_date",
    "death_sort_date_key",
    "living_flag",
    "private_flag",
)
_NOTE_COLUMNS = ("general_notes", "research_notes", "medical_notes", "cause_of_death")


def connect_read_only(database_path: str | PathLike[str]) -> sqlite3.Connection:
    """Open an existing SQLite database with writes disabled at the SQLite layer."""

    path = Path(database_path).expanduser().resolve(strict=True)
    connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only = ON")
    return connection


@contextmanager
def _connection(source: DatabaseSource) -> Iterator[sqlite3.Connection]:
    if isinstance(source, sqlite3.Connection):
        yield source
        return
    connection = connect_read_only(source)
    try:
        yield connection
    finally:
        connection.close()


def _json_value(value: Any) -> JsonValue:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _fetch_all(
    connection: sqlite3.Connection, sql: str, parameters: Sequence[Any] = ()
) -> list[JsonObject]:
    cursor = connection.execute(sql, tuple(parameters))
    names = [description[0] for description in cursor.description or ()]
    return [
        {name: _json_value(value) for name, value in zip(names, row, strict=True)}
        for row in cursor.fetchall()
    ]


def _fetch_one(
    connection: sqlite3.Connection, sql: str, parameters: Sequence[Any] = ()
) -> JsonObject | None:
    rows = _fetch_all(connection, sql, parameters)
    return rows[0] if rows else None


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?", (table,)
        ).fetchone()
        is not None
    )


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _columns(connection: sqlite3.Connection, table: str) -> tuple[str, ...]:
    if not _table_exists(connection, table):
        return ()
    quoted_table = _quote_identifier(table)
    return tuple(row[1] for row in connection.execute(f"PRAGMA table_info({quoted_table})"))


def _dataset_rows(connection: sqlite3.Connection, table: str, dataset_id: Any) -> list[JsonObject]:
    columns = _columns(connection, table)
    if not columns:
        return []
    if "dataset_id" in columns:
        return _fetch_all(
            connection,
            f"SELECT * FROM {_quote_identifier(table)} WHERE dataset_id = ?",
            (dataset_id,),
        )
    return _fetch_all(connection, f"SELECT * FROM {_quote_identifier(table)}")


def _first_column(columns: set[str], *candidates: str) -> str | None:
    return next((candidate for candidate in candidates if candidate in columns), None)


def _person_source(connection: sqlite3.Connection) -> tuple[str, set[str], str | None]:
    people_columns = set(_columns(connection, "people"))
    if "person_id" in people_columns:
        return "people", people_columns, "person_id"
    individual_columns = set(_columns(connection, "individuals"))
    if "individual_id" in individual_columns:
        return "individuals", individual_columns, "individual_id"
    return "people", people_columns, _first_column(people_columns, "person_id", "individual_id")


def _add_alias(row: JsonObject, target: str, *sources: str) -> None:
    if target in row:
        return
    for source in sources:
        if source in row:
            row[target] = row[source]
            return


def _normalize_person(person: JsonObject) -> JsonObject:
    result = dict(person)
    aliases = {
        "person_id": ("individual_id",),
        "legacy_rin": ("legacy_id",),
        "given_names": ("given_name",),
        "title_prefix": ("prefix",),
        "title_suffix": ("title",),
        "gender_code": ("gender",),
        "birth_legacy_date": ("birth_date",),
        "birth_sort_date_key": ("birth_sort_date",),
        "death_legacy_date": ("death_date",),
        "death_sort_date_key": ("death_sort_date",),
        "living_flag": ("living",),
        "private_flag": ("private",),
        "general_notes": ("notes",),
        "research_notes": ("references",),
        "medical_notes": ("medical",),
        "cause_of_death": ("death_cause",),
    }
    for target, sources in aliases.items():
        _add_alias(result, target, *sources)
    for name, value in tuple(result.items()):
        if name.endswith("_date") and not name.endswith("_sort_date"):
            result[f"{name}_display"] = decode_legacy_date(value)
    result["birth_date_display"] = decode_legacy_date(result.get("birth_legacy_date"))
    result["death_date_display"] = decode_legacy_date(result.get("death_legacy_date"))
    return result


def _display_name(person: Mapping[str, JsonValue]) -> str:
    parts = [str(person.get(column) or "").strip() for column in _PERSON_NAME_COLUMNS]
    name = " ".join(part for part in parts if part)
    return name or f"Person {person.get('person_id', '')}".strip()


def _person_summary(person: JsonObject) -> JsonObject:
    result = _normalize_person(person)
    result["display_name"] = _display_name(result)
    return result


def _person_reference(person: JsonObject) -> JsonObject:
    """Return the compact identity used in family and graph responses."""

    summary = _person_summary(person)
    fields = (
        "dataset_id",
        "person_id",
        "legacy_rin",
        "display_name",
        "title_prefix",
        "given_names",
        "surname",
        "title_suffix",
        "gender_code",
        "birth_legacy_date",
        "birth_sort_date_key",
        "birth_date_display",
        "death_legacy_date",
        "death_sort_date_key",
        "death_date_display",
        "living_flag",
        "private_flag",
    )
    return {field: summary.get(field) for field in fields if field in summary}


def _person(connection: sqlite3.Connection, dataset_id: Any, person_id: Any) -> JsonObject | None:
    table, columns, id_column = _person_source(connection)
    if "dataset_id" not in columns or id_column is None:
        return None
    row = _fetch_one(
        connection,
        f"SELECT * FROM {_quote_identifier(table)} WHERE dataset_id = ? "
        f"AND {_quote_identifier(id_column)} = ?",
        (dataset_id, person_id),
    )
    return _person_summary(row) if row else None


def list_datasets(source: DatabaseSource) -> list[JsonObject]:
    """Return every dataset, or inferred dataset IDs if metadata is absent."""

    with _connection(source) as connection:
        columns = _columns(connection, "datasets")
        if columns:
            order_column = _first_column(set(columns), "dataset_id", "id")
            order = f" ORDER BY {_quote_identifier(order_column)}" if order_column else ""
            rows = _fetch_all(connection, f"SELECT * FROM datasets{order}")
            for row in rows:
                _add_alias(row, "dataset_id", "id")
            return rows
        people_table, people_columns, _ = _person_source(connection)
        if "dataset_id" not in people_columns:
            return []
        return _fetch_all(
            connection,
            f"SELECT DISTINCT dataset_id FROM {_quote_identifier(people_table)} "
            "ORDER BY dataset_id",
        )


def _like_term(query: str) -> str:
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _name_expression(alias: str, columns: set[str]) -> str | None:
    name_columns = (
        _first_column(columns, "title_prefix", "prefix"),
        _first_column(columns, "given_names", "given_name"),
        _first_column(columns, "surname"),
        _first_column(columns, "title_suffix", "title"),
    )
    parts = [
        f"COALESCE(CAST({alias}.{_quote_identifier(column)} AS TEXT), '')"
        for column in name_columns
        if column is not None
    ]
    return " || ' ' || ".join(parts) if parts else None


def search_people(
    source: DatabaseSource,
    dataset_id: Any,
    query: str,
    *,
    limit: int = 50,
) -> list[JsonObject]:
    """Search primary and alternate names within one dataset."""

    limit = max(1, min(int(limit), 500))
    with _connection(source) as connection:
        people_table, people_columns, person_id_column = _person_source(connection)
        if "dataset_id" not in people_columns or person_id_column is None:
            return []
        terms = [_like_term(token) for token in query.split() if token]
        if not terms:
            return []
        primary_expression = _name_expression("p", people_columns)
        clauses = []
        parameters: list[Any] = [dataset_id]

        alternate_columns = set(_columns(connection, "alternate_names"))
        alternate_expression = _name_expression("a", alternate_columns)
        alternate_person_column = _first_column(alternate_columns, "person_id", "individual_id")
        dataset_join = ""
        if "dataset_id" in alternate_columns:
            dataset_join = " AND a.dataset_id = p.dataset_id"
        for term in terms:
            term_clauses = []
            if primary_expression:
                term_clauses.append(f"({primary_expression}) LIKE ? ESCAPE '\\' COLLATE NOCASE")
                parameters.append(term)
            if alternate_person_column and alternate_expression:
                term_clauses.append(
                    "EXISTS (SELECT 1 FROM alternate_names a "
                    f"WHERE a.{_quote_identifier(alternate_person_column)} = "
                    f"p.{_quote_identifier(person_id_column)}"
                    f"{dataset_join} AND ({alternate_expression}) "
                    "LIKE ? ESCAPE '\\' COLLATE NOCASE)"
                )
                parameters.append(term)
            if term_clauses:
                clauses.append("(" + " OR ".join(term_clauses) + ")")
        if not clauses:
            return []
        surname_column = _first_column(people_columns, "surname")
        given_column = _first_column(people_columns, "given_names", "given_name")
        order_parts: list[str] = []
        normalized_query = " ".join(query.split())
        if given_column and surname_column:
            given = f"COALESCE(p.{_quote_identifier(given_column)}, '')"
            surname = f"COALESCE(p.{_quote_identifier(surname_column)}, '')"
            primary_short = f"trim({given} || ' ' || {surname})"
            primary_reverse = f"trim({surname} || ' ' || {given})"
            primary_term_matches = " AND ".join(
                f"({primary_expression}) LIKE ? ESCAPE '\\' COLLATE NOCASE" for _ in terms
            )
            order_parts.append(
                "CASE "
                f"WHEN {primary_short} = ? COLLATE NOCASE "
                f"OR {primary_reverse} = ? COLLATE NOCASE THEN 0 "
                f"WHEN {given} = ? COLLATE NOCASE OR {surname} = ? COLLATE NOCASE THEN 1 "
                f"WHEN {primary_short} LIKE ? ESCAPE '\\' COLLATE NOCASE "
                f"OR {primary_reverse} LIKE ? ESCAPE '\\' COLLATE NOCASE THEN 2 "
                f"WHEN {primary_term_matches} THEN 3 ELSE 4 END"
            )
            parameters.extend(
                (
                    normalized_query,
                    normalized_query,
                    normalized_query,
                    normalized_query,
                    _like_term(normalized_query).removeprefix("%"),
                    _like_term(normalized_query).removeprefix("%"),
                    *terms,
                )
            )
        order_parts.extend(
            f"COALESCE(p.{_quote_identifier(column)}, '')"
            for column in (surname_column, given_column)
            if column is not None
        )
        order_parts.append(f"p.{_quote_identifier(person_id_column)}")
        parameters.append(limit)
        selected = [
            column
            for column in (
                "dataset_id",
                person_id_column,
                "legacy_id",
                "prefix",
                "given_name",
                "surname",
                "title",
                "gender",
                "birth_date",
                "birth_sort_date",
                "death_date",
                "death_sort_date",
                "living",
                "private",
            )
            if column in people_columns
        ]
        rows = _fetch_all(
            connection,
            "SELECT "
            + ", ".join(f"p.{_quote_identifier(column)}" for column in selected)
            + f" FROM {_quote_identifier(people_table)} p "
            "WHERE p.dataset_id = ? AND ("
            + " AND ".join(clauses)
            + ") ORDER BY "
            + ", ".join(order_parts)
            + " LIMIT ?",
            parameters,
        )
        return [_person_summary(row) for row in rows]


def list_people(
    source: DatabaseSource,
    dataset_id: Any,
    *,
    limit: int = 100,
    offset: int = 0,
) -> JsonObject:
    """Return one alphabetically sorted page of compact person records."""

    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    with _connection(source) as connection:
        people_table, people_columns, person_id_column = _person_source(connection)
        if "dataset_id" not in people_columns or person_id_column is None:
            return {"people": [], "total": 0, "limit": limit, "offset": offset, "has_more": False}
        selected = [
            column
            for column in (
                "dataset_id",
                person_id_column,
                "legacy_id",
                "prefix",
                "given_name",
                "surname",
                "title",
                "gender",
                "birth_date",
                "birth_sort_date",
                "death_date",
                "death_sort_date",
                "living",
                "private",
            )
            if column in people_columns
        ]
        total = int(
            connection.execute(
                f"SELECT count(*) FROM {_quote_identifier(people_table)} WHERE dataset_id=?",
                (dataset_id,),
            ).fetchone()[0]
        )
        surname_column = _first_column(people_columns, "surname")
        given_column = _first_column(people_columns, "given_names", "given_name")
        order_parts = [
            f"CASE WHEN p.{_quote_identifier(column)} IS NULL "
            f"OR p.{_quote_identifier(column)}='' THEN 1 ELSE 0 END"
            for column in (surname_column, given_column)
            if column is not None
        ]
        order_parts.extend(
            f"p.{_quote_identifier(column)} COLLATE NOCASE"
            for column in (surname_column, given_column)
            if column is not None
        )
        order_parts.append(f"p.{_quote_identifier(person_id_column)}")
        rows = _fetch_all(
            connection,
            "SELECT "
            + ", ".join(f"p.{_quote_identifier(column)}" for column in selected)
            + f" FROM {_quote_identifier(people_table)} p WHERE p.dataset_id=? ORDER BY "
            + ", ".join(order_parts)
            + " LIMIT ? OFFSET ?",
            (dataset_id, limit, offset),
        )
        people = [_person_summary(row) for row in rows]
        return {
            "people": people,
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": offset + len(people) < total,
        }


def get_person(source: DatabaseSource, dataset_id: Any, person_id: Any) -> JsonObject | None:
    """Return a person's identity and basic facts."""

    with _connection(source) as connection:
        return _person(connection, dataset_id, person_id)


def _rows_for_person(
    connection: sqlite3.Connection,
    table: str,
    dataset_id: Any,
    person_id: Any,
) -> list[JsonObject]:
    columns = set(_columns(connection, table))
    person_columns = [
        column
        for column in (
            "person_id",
            "individual_id",
            "subject_person_id",
            "owner_person_id",
            "owner_record_id",
        )
        if column in columns
    ]
    if not person_columns:
        return []
    clauses = [f"{_quote_identifier(column)} = ?" for column in person_columns]
    parameters: list[Any] = [person_id] * len(clauses)
    dataset_clause = ""
    if "dataset_id" in columns:
        dataset_clause = "dataset_id = ? AND "
        parameters.insert(0, dataset_id)
    return _fetch_all(
        connection,
        f"SELECT * FROM {_quote_identifier(table)} WHERE {dataset_clause}("
        + " OR ".join(clauses)
        + ")",
        parameters,
    )


def _rows_by_ids(
    connection: sqlite3.Connection,
    table: str,
    id_column: str,
    values: set[JsonValue],
    dataset_id: Any,
) -> list[JsonObject]:
    columns = set(_columns(connection, table))
    if id_column not in columns or not values:
        return []
    placeholders = ", ".join("?" for _ in values)
    parameters: list[Any] = list(values)
    dataset_clause = ""
    if "dataset_id" in columns:
        dataset_clause = "dataset_id = ? AND "
        parameters.insert(0, dataset_id)
    return _fetch_all(
        connection,
        f"SELECT * FROM {_quote_identifier(table)} WHERE {dataset_clause}"
        f"{_quote_identifier(id_column)} IN ({placeholders})",
        parameters,
    )


def _deduplicate(rows: list[JsonObject]) -> list[JsonObject]:
    result: list[JsonObject] = []
    seen: set[str] = set()
    for row in rows:
        marker = repr(sorted(row.items()))
        if marker not in seen:
            seen.add(marker)
            result.append(row)
    return result


def _event_facts(
    connection: sqlite3.Connection,
    dataset_id: Any,
    person_id: Any,
    legacy_rin: Any,
) -> tuple[list[JsonObject], set[JsonValue], set[JsonValue], set[JsonValue]]:
    participants = _rows_for_person(connection, "event_participants", dataset_id, person_id)
    event_ids = {row["event_id"] for row in participants if row.get("event_id") is not None}
    events = _rows_by_ids(connection, "events", "event_id", event_ids, dataset_id)
    direct_events = []
    event_columns = set(_columns(connection, "events"))
    if {"dataset_id", "owner_record_id", "record_type"} <= event_columns:
        direct_events = _fetch_all(
            connection,
            "SELECT * FROM events WHERE dataset_id=? AND record_type=0 AND owner_record_id=?",
            (dataset_id, legacy_rin),
        )
    events = _deduplicate(events + direct_events)
    event_ids.update(row["event_id"] for row in events if row.get("event_id") is not None)

    event_types = _rows_by_ids(
        connection,
        "event_types",
        "event_type_id",
        {row["event_type_id"] for row in events if row.get("event_type_id") is not None},
        dataset_id,
    )
    location_ids = {
        value
        for row in events
        for column in ("location_id", "event_location_id")
        if (value := row.get(column)) is not None
    }
    locations = _rows_by_ids(
        connection,
        "locations",
        "location_id",
        location_ids,
        dataset_id,
    )
    type_by_id = {row.get("event_type_id"): row for row in event_types}
    location_by_id = {row.get("location_id"): row for row in locations}
    participants_by_event: defaultdict[JsonValue, list[JsonObject]] = defaultdict(list)
    for participant in participants:
        participants_by_event[participant.get("event_id")].append(participant)

    enriched: list[JsonObject] = []
    for event in events:
        item = dict(event)
        event_id = event.get("event_id")
        item["participants"] = participants_by_event.get(event_id, [])
        event_type = type_by_id.get(event.get("event_type_id"))
        location = location_by_id.get(event.get("location_id") or event.get("event_location_id"))
        if event_type is not None:
            item["event_type"] = event_type
            event_type_name = next(
                (
                    event_type.get(column)
                    for column in ("event_type_name", "event_type", "name", "title")
                    if event_type.get(column) is not None
                ),
                None,
            )
            if event_type_name is not None:
                item["event_type_name"] = event_type_name
        if location is not None:
            item["location"] = location
            location_name = next(
                (
                    location.get(column)
                    for column in ("location_name", "location", "name", "place")
                    if location.get(column) is not None
                ),
                None,
            )
            if location_name is not None:
                item["location_name"] = location_name
        enriched.append(item)
    return enriched, event_ids, set(type_by_id), set(location_by_id)


def get_person_facts(source: DatabaseSource, dataset_id: Any, person_id: Any) -> JsonObject | None:
    """Return all descriptive person fields and optional attached records."""

    with _connection(source) as connection:
        person = _person(connection, dataset_id, person_id)
        if person is None:
            return None

        events, event_ids, _, _ = _event_facts(
            connection, dataset_id, person_id, person.get("legacy_rin")
        )
        alternate_names = _rows_for_person(connection, "alternate_names", dataset_id, person_id)
        child_links = _rows_for_person(connection, "children", dataset_id, person_id)
        marriages = []
        marriage_columns = set(_columns(connection, "marriages"))
        if {"dataset_id", "husband_individual_id", "wife_individual_id"} <= marriage_columns:
            marriages = _fetch_all(
                connection,
                "SELECT * FROM marriages WHERE dataset_id=? "
                "AND (husband_individual_id=? OR wife_individual_id=?)",
                (dataset_id, person_id, person_id),
            )
        participants = _rows_for_person(connection, "event_participants", dataset_id, person_id)
        story_links = _rows_for_person(connection, "story_individuals", dataset_id, person_id)
        todos = _rows_for_person(connection, "todos", dataset_id, person_id)
        citations = _person_citations(
            connection,
            dataset_id,
            person_id,
            event_ids=event_ids,
            alternate_name_ids={
                row["alternate_name_id"]
                for row in alternate_names
                if row.get("alternate_name_id") is not None
            },
            child_link_ids={
                row["child_id"] for row in child_links if row.get("child_id") is not None
            },
            marriage_ids={
                row["marriage_id"] for row in marriages if row.get("marriage_id") is not None
            },
            participant_ids={
                row["event_participant_id"]
                for row in participants
                if row.get("event_participant_id") is not None
            },
            story_ids={row["story_id"] for row in story_links if row.get("story_id") is not None},
            todo_ids={row["todo_id"] for row in todos if row.get("todo_id") is not None},
        )
        source_ids = {row["source_id"] for row in citations if row.get("source_id") is not None}
        sources = _rows_by_ids(connection, "sources", "source_id", source_ids, dataset_id)

        identity = {column: person.get(column) for column in _IDENTITY_COLUMNS if column in person}
        notes = {column: person.get(column) for column in _NOTE_COLUMNS if column in person}
        location_ids = {
            value
            for column, value in person.items()
            if column.endswith("_location_id") and value is not None
        }
        location_ids.update(
            value
            for event in events
            for column in ("location_id", "event_location_id")
            if (value := event.get(column)) is not None
        )
        stories = _rows_for_person(connection, "stories", dataset_id, person_id)
        stories += _rows_by_ids(
            connection,
            "stories",
            "story_id",
            {row["story_id"] for row in story_links if row.get("story_id") is not None},
            dataset_id,
        )
        result: JsonObject = {
            "person": person,
            "identity": identity,
            "notes": notes,
            "alternate_names": alternate_names,
            "events": events,
            "locations": _rows_by_ids(
                connection, "locations", "location_id", location_ids, dataset_id
            ),
            "citations": citations,
            "sources": sources,
            "media": _rows_for_person(connection, "media", dataset_id, person_id),
            "stories": _deduplicate(stories),
            "todo": todos,
        }
        return result


def _person_citations(
    connection: sqlite3.Connection,
    dataset_id: Any,
    person_id: Any,
    *,
    event_ids: set[JsonValue],
    alternate_name_ids: set[JsonValue],
    child_link_ids: set[JsonValue],
    marriage_ids: set[JsonValue],
    participant_ids: set[JsonValue],
    story_ids: set[JsonValue],
    todo_ids: set[JsonValue],
) -> list[JsonObject]:
    """Resolve Legacy's polymorphic citation target for one person."""

    if not _table_exists(connection, "citations"):
        return []
    target_groups = (
        ({0, 1, 2, 3, 4, 5, 15, 16, 26, 27}, {person_id}),
        ({10}, alternate_name_ids),
        ({12, 13}, todo_ids),
        ({17}, child_link_ids),
        ({18, 20}, marriage_ids),
        ({28}, story_ids),
        ({30}, event_ids),
        ({31}, participant_ids),
    )
    clauses: list[str] = []
    parameters: list[Any] = [dataset_id]
    for type_codes, record_ids in target_groups:
        if not record_ids:
            continue
        clauses.append(
            "(type IN ("
            + ", ".join("?" for _ in type_codes)
            + ") AND cited_record_id IN ("
            + ", ".join("?" for _ in record_ids)
            + "))"
        )
        parameters.extend(sorted(type_codes))
        parameters.extend(record_ids)
    if not clauses:
        return []
    return _fetch_all(
        connection,
        "SELECT * FROM citations WHERE dataset_id=? AND (" + " OR ".join(clauses) + ")",
        parameters,
    )


def _id_map(rows: list[JsonObject], id_column: str) -> dict[JsonValue, JsonObject]:
    return {row[id_column]: row for row in rows if row.get(id_column) is not None}


_IN_CHUNK_SIZE = 900


def _value_order(value: JsonValue) -> tuple[int, float | str]:
    if isinstance(value, (int, float)):
        return (0, float(value))
    if value is None:
        return (2, "")
    return (1, str(value))


def _ordered_values(values: Sequence[JsonValue]) -> list[JsonValue]:
    seen: set[JsonValue] = set()
    result = []
    for value in values:
        if value is not None and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _rows_with_values(
    connection: sqlite3.Connection,
    table: str,
    dataset_id: Any,
    column: str,
    values: Sequence[JsonValue],
    *,
    selected_columns: Sequence[str] | None = None,
) -> list[JsonObject]:
    values = _ordered_values(values)
    if not values:
        return []
    selection = "*"
    if selected_columns is not None:
        selection = ", ".join(_quote_identifier(name) for name in selected_columns)
    rows: list[JsonObject] = []
    for offset in range(0, len(values), _IN_CHUNK_SIZE):
        chunk = values[offset : offset + _IN_CHUNK_SIZE]
        placeholders = ", ".join("?" for _ in chunk)
        rows.extend(
            _fetch_all(
                connection,
                f"SELECT {selection} FROM {_quote_identifier(table)} "
                f"WHERE dataset_id = ? AND {_quote_identifier(column)} IN ({placeholders})",
                (dataset_id, *chunk),
            )
        )
    return rows


def _compact_people(
    connection: sqlite3.Connection, dataset_id: Any, person_ids: Sequence[JsonValue]
) -> dict[JsonValue, JsonObject]:
    table, columns, id_column = _person_source(connection)
    if "dataset_id" not in columns or id_column is None:
        return {}
    candidates = (
        "dataset_id",
        id_column,
        "legacy_rin",
        "legacy_id",
        "title_prefix",
        "prefix",
        "given_names",
        "given_name",
        "surname",
        "title_suffix",
        "title",
        "gender_code",
        "gender",
        "birth_legacy_date",
        "birth_date",
        "birth_sort_date_key",
        "birth_sort_date",
        "death_legacy_date",
        "death_date",
        "death_sort_date_key",
        "death_sort_date",
        "living_flag",
        "living",
        "private_flag",
        "private",
    )
    selected = tuple(dict.fromkeys(column for column in candidates if column in columns))
    rows = _rows_with_values(
        connection,
        table,
        dataset_id,
        id_column,
        person_ids,
        selected_columns=selected,
    )
    return _id_map([_normalize_person(row) for row in rows], "person_id")


def _matching_person_id(
    people: Mapping[JsonValue, JsonObject], requested_id: Any
) -> JsonValue | None:
    if requested_id in people:
        return requested_id
    return next((key for key in people if str(key) == str(requested_id)), None)


def _normalize_marriage(marriage: JsonObject) -> JsonObject:
    _add_alias(marriage, "husband_person_id", "husband_individual_id")
    _add_alias(marriage, "wife_person_id", "wife_individual_id")
    _add_alias(marriage, "private_flag", "private")
    return marriage


def _normalize_link(link: JsonObject) -> JsonObject:
    _add_alias(link, "parent_marriage_id", "marriage_id")
    _add_alias(link, "child_person_id", "individual_id", "child_individual_id")
    _add_alias(link, "child_order", "display_order")
    return link


def _marriage_columns(connection: sqlite3.Connection) -> tuple[set[str], str | None, str | None]:
    columns = set(_columns(connection, "marriages"))
    return (
        columns,
        _first_column(columns, "husband_person_id", "husband_individual_id"),
        _first_column(columns, "wife_person_id", "wife_individual_id"),
    )


def _marriage_order(marriage: JsonObject) -> tuple[int, float | str]:
    return _value_order(marriage.get("marriage_id"))


def _link_order(
    link: JsonObject,
) -> tuple[tuple[int, float | str], tuple[int, float | str], tuple[int, float | str]]:
    link_id = next(
        (
            link.get(column)
            for column in ("child_id", "parent_child_link_id", "link_id")
            if link.get(column) is not None
        ),
        None,
    )
    return (
        _value_order(link.get("parent_marriage_id")),
        _value_order(link.get("child_order")),
        _value_order(link_id if link_id is not None else link.get("child_person_id")),
    )


def _marriage_rows_by_ids(
    connection: sqlite3.Connection,
    dataset_id: Any,
    marriage_ids: Sequence[JsonValue],
    *,
    full: bool = False,
) -> list[JsonObject]:
    columns, husband_column, wife_column = _marriage_columns(connection)
    if "dataset_id" not in columns or "marriage_id" not in columns:
        return []
    selected = None
    if not full:
        selected = tuple(
            column
            for column in ("dataset_id", "marriage_id", husband_column, wife_column)
            if column is not None
        )
    rows = _rows_with_values(
        connection,
        "marriages",
        dataset_id,
        "marriage_id",
        marriage_ids,
        selected_columns=selected,
    )
    rows = [_normalize_marriage(row) for row in rows]
    rows.sort(key=_marriage_order)
    return rows


def _own_marriages(
    connection: sqlite3.Connection,
    dataset_id: Any,
    person_ids: Sequence[JsonValue],
    *,
    full: bool = False,
) -> list[JsonObject]:
    columns, husband_column, wife_column = _marriage_columns(connection)
    if "dataset_id" not in columns or husband_column is None or wife_column is None:
        return []
    selected = None
    if not full:
        selected = tuple(
            column
            for column in ("dataset_id", "marriage_id", husband_column, wife_column)
            if column is not None
        )
    rows: list[JsonObject] = []
    # Separate branches let SQLite use each spouse-column index.
    for column in (husband_column, wife_column):
        rows.extend(
            _rows_with_values(
                connection,
                "marriages",
                dataset_id,
                column,
                person_ids,
                selected_columns=selected,
            )
        )
    unique: dict[tuple[JsonValue, JsonValue, JsonValue], JsonObject] = {}
    for row in rows:
        marriage = _normalize_marriage(row)
        key = (
            marriage.get("marriage_id"),
            marriage.get("husband_person_id"),
            marriage.get("wife_person_id"),
        )
        unique.setdefault(key, marriage)
    result = list(unique.values())
    result.sort(key=_marriage_order)
    return result


def _link_source(connection: sqlite3.Connection) -> tuple[str, set[str], str | None, str | None]:
    table = "parent_child_links" if _table_exists(connection, "parent_child_links") else "children"
    columns = set(_columns(connection, table))
    return (
        table,
        columns,
        _first_column(columns, "parent_marriage_id", "marriage_id"),
        _first_column(columns, "child_person_id", "individual_id", "child_individual_id"),
    )


def _links_by_column(
    connection: sqlite3.Connection,
    dataset_id: Any,
    column: str | None,
    values: Sequence[JsonValue],
) -> list[JsonObject]:
    table, columns, _, _ = _link_source(connection)
    if "dataset_id" not in columns or column is None:
        return []
    rows = _rows_with_values(connection, table, dataset_id, column, values)
    rows = [_normalize_link(row) for row in rows]
    rows.sort(key=_link_order)
    return rows


def _parent_links(
    connection: sqlite3.Connection, dataset_id: Any, person_ids: Sequence[JsonValue]
) -> list[JsonObject]:
    _, _, _, child_column = _link_source(connection)
    return _links_by_column(connection, dataset_id, child_column, person_ids)


def _marriage_links(
    connection: sqlite3.Connection, dataset_id: Any, marriage_ids: Sequence[JsonValue]
) -> list[JsonObject]:
    _, _, marriage_column, _ = _link_source(connection)
    return _links_by_column(connection, dataset_id, marriage_column, marriage_ids)


def _with_relationship(
    person: JsonObject,
    relationship: str,
    marriage_id: JsonValue | None = None,
) -> JsonObject:
    result = _person_reference(person)
    result["relationship"] = relationship
    if marriage_id is not None:
        result["through_marriage_id"] = marriage_id
    return result


def _unique_people(rows: list[JsonObject]) -> list[JsonObject]:
    seen: set[JsonValue] = set()
    result = []
    for row in rows:
        person_id = row.get("person_id")
        if person_id not in seen:
            seen.add(person_id)
            result.append(row)
    return result


def get_ancestor_family_tree(
    source: DatabaseSource,
    dataset_id: Any,
    first_person_id: Any,
    second_person_id: Any | None = None,
    max_depth: int = 3,
) -> JsonObject | None:
    """Return an ancestor-focused graph rooted at a couple or one person."""

    max_depth = max(0, min(int(max_depth), 6))
    requested_ids = [first_person_id]
    if second_person_id is not None:
        requested_ids.append(second_person_id)

    with _connection(source) as connection:
        people = _compact_people(connection, dataset_id, requested_ids)
        root_ids: list[JsonValue] = []
        for requested_id in requested_ids:
            person_id = _matching_person_id(people, requested_id)
            if person_id is None:
                return None
            root_ids.append(person_id)
        if len(root_ids) == 2 and root_ids[0] == root_ids[1]:
            raise ValueError("first and second must identify two different people")

        root_set = set(root_ids)
        if len(root_ids) == 2:
            root_marriages = _own_marriages(connection, dataset_id, [root_ids[0]], full=True)
            shared_marriages = [
                marriage
                for marriage in root_marriages
                if {
                    marriage.get("husband_person_id"),
                    marriage.get("wife_person_id"),
                }
                == root_set
            ]
            if not shared_marriages:
                root_references = [_person_reference(people[person_id]) for person_id in root_ids]
                root_parent_links = _parent_links(connection, dataset_id, root_ids)
                roots_with_parents = sorted(
                    {
                        link["child_person_id"]
                        for link in root_parent_links
                        if link.get("child_person_id") in root_set
                    },
                    key=_value_order,
                )
                return {
                    "status": "no_shared_couple",
                    "message": "The requested people do not share a recorded marriage in this dataset.",
                    "dataset_id": dataset_id,
                    "max_depth": max_depth,
                    "truncated": bool(roots_with_parents),
                    "roots": root_references,
                    "people": root_references,
                    "couples": [],
                    "links": [],
                    "has_parents": roots_with_parents,
                    "counts": {
                        "people": len(root_references),
                        "couples": 0,
                        "links": 0,
                        "generations": 1,
                    },
                }
        else:
            root_id = root_ids[0]
            shared_marriages = [
                {
                    "dataset_id": dataset_id,
                    "marriage_id": f"root:{root_id}",
                    "husband_person_id": root_id,
                    "wife_person_id": None,
                }
            ]
        synthetic_root_id = f"root:{root_ids[0]}" if len(root_ids) == 1 else None

        couple_entries: dict[JsonValue, tuple[JsonObject, int, bool]] = {}
        for marriage in shared_marriages:
            marriage_id = marriage.get("marriage_id")
            if marriage_id is not None:
                couple_entries[marriage_id] = (marriage, 0, True)

        ancestor_depths: dict[JsonValue, int] = {person_id: 0 for person_id in root_ids}
        frontier = list(root_ids)
        expanded: set[JsonValue] = set()
        has_parents: set[JsonValue] = set()
        links: list[JsonObject] = []
        seen_links: set[tuple[JsonValue, JsonValue]] = set()
        truncated = False

        for depth in range(max_depth + 1):
            current = [person_id for person_id in frontier if person_id not in expanded]
            if not current:
                break
            expanded.update(current)
            parent_links = _parent_links(connection, dataset_id, current)
            current_set = set(current)
            has_parents.update(
                link["child_person_id"]
                for link in parent_links
                if link.get("child_person_id") in current_set
            )
            if depth == max_depth:
                truncated = bool(parent_links)
                break

            marriage_ids = _ordered_values(
                [link.get("parent_marriage_id") for link in parent_links]
            )
            marriages = _marriage_rows_by_ids(connection, dataset_id, marriage_ids, full=True)
            marriage_by_id = _id_map(marriages, "marriage_id")
            links_by_child: defaultdict[JsonValue, list[JsonObject]] = defaultdict(list)
            for link in parent_links:
                links_by_child[link.get("child_person_id")].append(link)

            candidate_parent_ids: list[JsonValue] = []
            for child_id in sorted(current, key=_value_order):
                for parent_link in links_by_child.get(child_id, []):
                    marriage_id = parent_link.get("parent_marriage_id")
                    marriage = marriage_by_id.get(marriage_id)
                    if marriage is None or marriage_id is None:
                        continue
                    partner_ids = [
                        person_id
                        for person_id in (
                            marriage.get("husband_person_id"),
                            marriage.get("wife_person_id"),
                        )
                        if person_id is not None
                    ]
                    # A parent already at this or a younger depth would make a graph cycle.
                    if any(
                        person_id == child_id
                        or (person_id in ancestor_depths and ancestor_depths[person_id] <= depth)
                        for person_id in partner_ids
                    ):
                        continue

                    existing_couple = couple_entries.get(marriage_id)
                    if existing_couple is not None and existing_couple[1] <= depth:
                        continue
                    if existing_couple is None:
                        couple_entries[marriage_id] = (marriage, depth + 1, False)

                    link_key = (child_id, marriage_id)
                    if link_key not in seen_links:
                        seen_links.add(link_key)
                        links.append(
                            {
                                "child_person_id": child_id,
                                "parent_couple_id": marriage_id,
                                "depth": depth + 1,
                            }
                        )
                    candidate_parent_ids.extend(partner_ids)

            fetched_parents = _compact_people(connection, dataset_id, candidate_parent_ids)
            people.update(fetched_parents)
            next_frontier: list[JsonValue] = []
            for person_id in _ordered_values(candidate_parent_ids):
                if person_id not in fetched_parents and person_id not in people:
                    continue
                if person_id not in ancestor_depths:
                    ancestor_depths[person_id] = depth + 1
                    next_frontier.append(person_id)
            frontier = next_frontier

        ordered_couples = sorted(
            couple_entries.values(),
            key=lambda entry: (entry[1], _value_order(entry[0].get("marriage_id"))),
        )
        recorded_marriage_ids = [
            marriage.get("marriage_id")
            for marriage, _, _ in ordered_couples
            if marriage.get("marriage_id") != synthetic_root_id
        ]
        child_links = _marriage_links(connection, dataset_id, recorded_marriage_ids)
        children_by_marriage: defaultdict[JsonValue, list[JsonValue]] = defaultdict(list)
        for child_link in child_links:
            child_id = child_link.get("child_person_id")
            if child_id is not None:
                children_by_marriage[child_link.get("parent_marriage_id")].append(child_id)

        visible_partner_ids = _ordered_values(
            [
                person_id
                for marriage, _, _ in ordered_couples
                for person_id in (
                    marriage.get("husband_person_id"),
                    marriage.get("wife_person_id"),
                )
                if person_id is not None
            ]
        )
        own_marriages = _own_marriages(connection, dataset_id, visible_partner_ids)
        marriages_by_partner: defaultdict[JsonValue, list[JsonObject]] = defaultdict(list)
        alternate_spouse_ids: list[JsonValue] = []
        for marriage in own_marriages:
            husband_id = marriage.get("husband_person_id")
            wife_id = marriage.get("wife_person_id")
            for partner_id, spouse_id in ((husband_id, wife_id), (wife_id, husband_id)):
                if partner_id is not None:
                    marriages_by_partner[partner_id].append(marriage)
                    if spouse_id is not None:
                        alternate_spouse_ids.append(spouse_id)

        menu_person_ids = [
            child_id for child_ids in children_by_marriage.values() for child_id in child_ids
        ]
        people.update(
            _compact_people(
                connection,
                dataset_id,
                [*menu_person_ids, *alternate_spouse_ids],
            )
        )

        couples: list[JsonObject] = []
        referenced_ids: set[JsonValue] = set(ancestor_depths)
        for marriage, depth, root_couple in ordered_couples:
            marriage_id = marriage.get("marriage_id")
            partner_ids = [
                person_id
                for person_id in (
                    marriage.get("husband_person_id"),
                    marriage.get("wife_person_id"),
                )
                if person_id is not None
            ]
            child_ids = _ordered_values(children_by_marriage.get(marriage_id, []))
            alternatives: list[JsonObject] = []
            for partner_id in partner_ids:
                for alternate in marriages_by_partner.get(partner_id, []):
                    alternate_marriage_id = alternate.get("marriage_id")
                    if alternate_marriage_id == marriage_id:
                        continue
                    spouse_id = (
                        alternate.get("wife_person_id")
                        if alternate.get("husband_person_id") == partner_id
                        else alternate.get("husband_person_id")
                    )
                    if spouse_id not in people:
                        continue
                    referenced_ids.add(spouse_id)
                    alternatives.append(
                        {
                            "partner_person_id": partner_id,
                            "marriage_id": alternate_marriage_id,
                            "spouse_person_id": spouse_id,
                            "spouse": _person_reference(people[spouse_id]),
                        }
                    )
            alternatives.sort(
                key=lambda alternative: (
                    partner_ids.index(alternative["partner_person_id"]),
                    _value_order(alternative["marriage_id"]),
                    _value_order(alternative["spouse_person_id"]),
                )
            )
            referenced_ids.update(partner_ids)
            referenced_ids.update(child_id for child_id in child_ids if child_id in people)
            couple: JsonObject = {
                field: marriage.get(field)
                for field in (
                    "dataset_id",
                    "marriage_id",
                    "legacy_id",
                    "marriage_date",
                    "marriage_sort_date",
                    "marriage_end_date",
                    "marriage_end_sort_date",
                    "marriage_status_id",
                    "not_married",
                    "no_children",
                    "private_flag",
                )
                if field in marriage
            }
            couple.update(
                {
                    "depth": depth,
                    "root_couple": root_couple,
                    "partner_person_ids": partner_ids,
                    "partners": [
                        _person_reference(people[person_id])
                        for person_id in partner_ids
                        if person_id in people
                    ],
                    "child_ids": child_ids,
                    "children": [
                        _person_reference(people[child_id])
                        for child_id in child_ids
                        if child_id in people
                    ],
                    "alternative_spouses": alternatives,
                }
            )
            couples.append(couple)

        visible_ids = sorted(
            (person_id for person_id in ancestor_depths if person_id in people),
            key=lambda person_id: (ancestor_depths[person_id], _value_order(person_id)),
        )
        menu_ids = sorted(
            (person_id for person_id in referenced_ids - set(visible_ids) if person_id in people),
            key=_value_order,
        )
        person_items: list[JsonObject] = []
        for person_id in [*visible_ids, *menu_ids]:
            person = _person_reference(people[person_id])
            if person_id in ancestor_depths:
                person["depth"] = ancestor_depths[person_id]
            person_items.append(person)

        links.sort(
            key=lambda link: (
                link["depth"],
                _value_order(link["parent_couple_id"]),
                _value_order(link["child_person_id"]),
            )
        )
        generation_depths = {0, *(depth for _, depth, _ in ordered_couples)}
        return {
            "status": "ok",
            "message": None,
            "dataset_id": dataset_id,
            "max_depth": max_depth,
            "truncated": truncated,
            "roots": [_person_reference(people[person_id]) for person_id in root_ids],
            "people": person_items,
            "couples": couples,
            "links": links,
            "has_parents": sorted(has_parents, key=_value_order),
            "counts": {
                "people": len(person_items),
                "couples": len(couples),
                "links": len(links),
                "generations": len(generation_depths),
            },
        }


def get_descendant_family_tree(
    source: DatabaseSource,
    dataset_id: Any,
    first_person_id: Any,
    second_person_id: Any,
    max_depth: int = 100,
) -> JsonObject | None:
    """Return a couple's complete descendant families, including descendant spouses."""

    max_depth = max(0, min(int(max_depth), 100))
    with _connection(source) as connection:
        people = _compact_people(connection, dataset_id, [first_person_id, second_person_id])
        first_id = _matching_person_id(people, first_person_id)
        second_id = _matching_person_id(people, second_person_id)
        if first_id is None or second_id is None:
            return None
        if first_id == second_id:
            raise ValueError("first and second must identify two different people")

        root_ids = [first_id, second_id]
        root_set = set(root_ids)
        roles: dict[JsonValue, str] = {person_id: "root" for person_id in root_ids}
        depths: dict[JsonValue, int] = {person_id: 0 for person_id in root_ids}
        expanded_descendants: set[JsonValue] = set()
        family_entries: list[tuple[JsonObject, int, bool, list[JsonValue], bool]] = []
        links: list[JsonObject] = []
        seen_families: set[tuple[JsonValue, JsonValue, JsonValue]] = set()
        seen_links: set[tuple[JsonValue, JsonValue]] = set()
        truncated = False

        def family_key(marriage: JsonObject) -> tuple[JsonValue, JsonValue, JsonValue]:
            return (
                marriage.get("marriage_id"),
                marriage.get("husband_person_id"),
                marriage.get("wife_person_id"),
            )

        def add_families(
            marriages: Sequence[JsonObject],
            depth: int,
            *,
            root_union: bool,
            include_children: bool,
        ) -> list[JsonValue]:
            nonlocal truncated
            new_marriages = [
                marriage for marriage in marriages if family_key(marriage) not in seen_families
            ]
            for marriage in new_marriages:
                seen_families.add(family_key(marriage))
            marriage_ids = _ordered_values(
                [marriage.get("marriage_id") for marriage in new_marriages]
            )
            marriage_links = _marriage_links(connection, dataset_id, marriage_ids)
            links_by_marriage: defaultdict[JsonValue, list[JsonObject]] = defaultdict(list)
            for link in marriage_links:
                links_by_marriage[link.get("parent_marriage_id")].append(link)

            related_ids = [
                person_id
                for marriage in new_marriages
                for person_id in (
                    marriage.get("husband_person_id"),
                    marriage.get("wife_person_id"),
                )
                if person_id is not None
            ]
            if include_children:
                related_ids.extend(
                    link.get("child_person_id")
                    for link in marriage_links
                    if link.get("child_person_id") is not None
                )
            people.update(
                _compact_people(
                    connection,
                    dataset_id,
                    [person_id for person_id in related_ids if person_id not in people],
                )
            )

            next_frontier: list[JsonValue] = []
            next_seen: set[JsonValue] = set()
            for marriage in new_marriages:
                marriage_id = marriage.get("marriage_id")
                partner_ids = [
                    person_id
                    for person_id in (
                        marriage.get("husband_person_id"),
                        marriage.get("wife_person_id"),
                    )
                    if person_id is not None
                ]
                for partner_id in partner_ids:
                    if partner_id not in people or partner_id in roles:
                        continue
                    roles[partner_id] = "spouse"
                    depths[partner_id] = depth

                child_ids: list[JsonValue] = []
                marriage_child_links = links_by_marriage.get(marriage_id, [])
                if not include_children and marriage_child_links:
                    truncated = True
                if include_children:
                    for link in marriage_child_links:
                        child_id = link.get("child_person_id")
                        if child_id not in people:
                            continue
                        child_ids.append(child_id)
                        if child_id not in root_set:
                            if roles.get(child_id) == "descendant":
                                depths[child_id] = min(depths[child_id], depth + 1)
                            else:
                                roles[child_id] = "descendant"
                                depths[child_id] = depth + 1
                            if child_id not in expanded_descendants and child_id not in next_seen:
                                next_seen.add(child_id)
                                next_frontier.append(child_id)
                        link_key = (marriage_id, child_id)
                        if link_key in seen_links:
                            continue
                        seen_links.add(link_key)
                        tree_link: JsonObject = {
                            "marriage_id": marriage_id,
                            "parent_marriage_id": marriage_id,
                            "from_person_ids": partner_ids,
                            "parent_person_ids": partner_ids,
                            "to_person_id": child_id,
                            "child_person_id": child_id,
                            "relationship": "child",
                            "depth": depth + 1,
                        }
                        privacy_flags = {
                            name: value for name, value in link.items() if "private" in name
                        }
                        if privacy_flags:
                            tree_link["privacy_flags"] = privacy_flags
                        links.append(tree_link)
                family_entries.append(
                    (
                        marriage,
                        depth,
                        root_union,
                        _ordered_values(child_ids),
                        not include_children and bool(marriage_child_links),
                    )
                )
            return next_frontier

        root_marriages = _own_marriages(connection, dataset_id, [first_id], full=True)
        shared_marriages = [
            marriage
            for marriage in root_marriages
            if {
                marriage.get("husband_person_id"),
                marriage.get("wife_person_id"),
            }
            == root_set
        ]

        if shared_marriages:
            frontier = add_families(
                shared_marriages,
                0,
                root_union=True,
                include_children=max_depth >= 1,
            )
            depth = 1
            while frontier and depth <= max_depth:
                current = [
                    person_id for person_id in frontier if person_id not in expanded_descendants
                ]
                expanded_descendants.update(current)
                marriages = _own_marriages(connection, dataset_id, current, full=True)
                frontier = add_families(
                    marriages,
                    depth,
                    root_union=False,
                    include_children=depth < max_depth,
                )
                depth += 1

        role_order = {"root": 0, "descendant": 1, "spouse": 2}
        ordered_person_ids = sorted(
            roles,
            key=lambda person_id: (
                depths[person_id],
                role_order[roles[person_id]],
                _value_order(person_id),
            ),
        )
        person_items: dict[JsonValue, JsonObject] = {}
        for person_id in ordered_person_ids:
            item = _person_reference(people[person_id])
            item["depth"] = depths[person_id]
            item["role"] = roles[person_id]
            person_items[person_id] = item

        families: list[JsonObject] = []
        for marriage, depth, root_union, child_ids, children_truncated in family_entries:
            husband_id = marriage.get("husband_person_id")
            wife_id = marriage.get("wife_person_id")
            family = {
                field: marriage.get(field)
                for field in (
                    "dataset_id",
                    "marriage_id",
                    "legacy_id",
                    "marriage_date",
                    "marriage_sort_date",
                    "marriage_end_date",
                    "marriage_end_sort_date",
                    "marriage_status_id",
                    "not_married",
                    "no_children",
                    "private_flag",
                )
                if field in marriage
            }
            family.update(
                {
                    "depth": depth,
                    "root_union": root_union,
                    "husband_person_id": husband_id,
                    "wife_person_id": wife_id,
                    "partner_person_ids": [
                        person_id for person_id in (husband_id, wife_id) if person_id is not None
                    ],
                    "husband": (
                        _person_reference(people[husband_id]) if husband_id in people else None
                    ),
                    "wife": _person_reference(people[wife_id]) if wife_id in people else None,
                    "partners": [
                        _person_reference(people[person_id])
                        for person_id in (husband_id, wife_id)
                        if person_id in people
                    ],
                    "child_ids": child_ids,
                    "children_truncated": children_truncated,
                }
            )
            if "marriage_date" in family:
                family["marriage_date_display"] = decode_legacy_date(family["marriage_date"])
            if "marriage_end_date" in family:
                family["marriage_end_date_display"] = decode_legacy_date(
                    family["marriage_end_date"]
                )
            families.append(family)

        for link in links:
            child_id = link.get("child_person_id")
            parent_ids = link.get("parent_person_ids")
            if not isinstance(parent_ids, list):
                parent_ids = []
            link["parent_references"] = [
                _person_reference(people[parent_id])
                for parent_id in parent_ids
                if parent_id in people
            ]
            link["child"] = _person_reference(people[child_id]) if child_id in people else None

        generations = []
        for depth in sorted(set(depths.values())):
            generation_ids = [
                person_id for person_id in ordered_person_ids if depths[person_id] == depth
            ]
            generations.append(
                {
                    "depth": depth,
                    "person_ids": generation_ids,
                    "people": [person_items[person_id] for person_id in generation_ids],
                }
            )

        status = "ok" if shared_marriages else "no_shared_union"
        payload: JsonObject = {
            "status": status,
            "message": (
                None
                if shared_marriages
                else "The root people do not share a marriage union in this dataset."
            ),
            "dataset_id": dataset_id,
            "max_depth": max_depth,
            "truncated": truncated,
            "roots": [_person_reference(people[person_id]) for person_id in root_ids],
            "people": [person_items[person_id] for person_id in ordered_person_ids],
            "families": families,
            "links": links,
            "generations": generations,
            "counts": {
                "roots": len(root_ids),
                "descendants": sum(role == "descendant" for role in roles.values()),
                "spouses": sum(role == "spouse" for role in roles.values()),
                "people": len(roles),
                "families": len(families),
                "links": len(links),
                "generations": len(generations),
            },
        }
        return payload


def get_family(source: DatabaseSource, dataset_id: Any, person_id: Any) -> JsonObject | None:
    """Return parents, spouses, children, and siblings for one person."""

    with _connection(source) as connection:
        people = _compact_people(connection, dataset_id, [person_id])
        actual_id = _matching_person_id(people, person_id)
        if actual_id is None:
            return None
        person = people[actual_id]
        own_marriages = _own_marriages(connection, dataset_id, [actual_id], full=True)
        parent_links = _parent_links(connection, dataset_id, [actual_id])
        parent_marriage_ids = _ordered_values(
            [link.get("parent_marriage_id") for link in parent_links]
        )
        parent_marriages = _marriage_rows_by_ids(connection, dataset_id, parent_marriage_ids)
        marriage_by_id = _id_map(parent_marriages, "marriage_id")
        own_marriage_ids = _ordered_values(
            [marriage.get("marriage_id") for marriage in own_marriages]
        )
        child_links = _marriage_links(connection, dataset_id, own_marriage_ids)
        sibling_links = _marriage_links(connection, dataset_id, parent_marriage_ids)

        related_ids: list[JsonValue] = []
        for marriage in (*parent_marriages, *own_marriages):
            related_ids.extend([marriage.get("husband_person_id"), marriage.get("wife_person_id")])
        related_ids.extend(link.get("child_person_id") for link in child_links)
        related_ids.extend(link.get("child_person_id") for link in sibling_links)
        people.update(_compact_people(connection, dataset_id, related_ids))

        parents: list[JsonObject] = []
        for marriage_id in parent_marriage_ids:
            marriage = marriage_by_id.get(marriage_id)
            if not marriage:
                continue
            for parent_id in (
                marriage.get("husband_person_id"),
                marriage.get("wife_person_id"),
            ):
                if parent_id in people:
                    parents.append(_with_relationship(people[parent_id], "parent", marriage_id))

        spouses: list[JsonObject] = []
        children: list[JsonObject] = []
        for marriage in own_marriages:
            spouse_id = (
                marriage.get("wife_person_id")
                if marriage.get("husband_person_id") == actual_id
                else marriage.get("husband_person_id")
            )
            if spouse_id in people:
                spouses.append(
                    _with_relationship(people[spouse_id], "spouse", marriage.get("marriage_id"))
                )
        for link in child_links:
            child_id = link.get("child_person_id")
            if child_id in people:
                children.append(
                    _with_relationship(people[child_id], "child", link.get("parent_marriage_id"))
                )

        siblings: list[JsonObject] = []
        for link in sibling_links:
            if link.get("child_person_id") != actual_id and link.get("child_person_id") in people:
                siblings.append(
                    _with_relationship(
                        people[link["child_person_id"]],
                        "sibling",
                        link.get("parent_marriage_id"),
                    )
                )

        return {
            "person": _person_reference(person),
            "parents": _unique_people(parents),
            "spouses": _unique_people(spouses),
            "children": _unique_people(children),
            "siblings": _unique_people(siblings),
            "marriages": own_marriages,
        }


def _frontier_edges(
    connection: sqlite3.Connection,
    dataset_id: Any,
    frontier: Sequence[JsonValue],
    *,
    relationships: set[str],
) -> dict[JsonValue, list[tuple[JsonValue, str, JsonValue | None]]]:
    edges: defaultdict[JsonValue, list[tuple[JsonValue, str, JsonValue | None]]] = defaultdict(list)
    frontier_set = set(frontier)
    parent_links = (
        _parent_links(connection, dataset_id, frontier) if "parent" in relationships else []
    )
    own_marriages = (
        _own_marriages(connection, dataset_id, frontier)
        if relationships & {"child", "spouse"}
        else []
    )
    parent_marriage_ids = _ordered_values([link.get("parent_marriage_id") for link in parent_links])
    child_links = (
        _marriage_links(
            connection,
            dataset_id,
            [marriage.get("marriage_id") for marriage in own_marriages],
        )
        if "child" in relationships
        else []
    )
    parent_marriages = _marriage_rows_by_ids(connection, dataset_id, parent_marriage_ids)
    marriage_by_id = _id_map([*parent_marriages, *own_marriages], "marriage_id")

    links = [*parent_links, *child_links]
    links.sort(key=_link_order)
    for link in links:
        marriage_id = link.get("parent_marriage_id")
        child_id = link.get("child_person_id")
        marriage = marriage_by_id.get(marriage_id)
        if not marriage:
            continue
        if "parent" in relationships and child_id in frontier_set:
            for parent_id in (
                marriage.get("husband_person_id"),
                marriage.get("wife_person_id"),
            ):
                if parent_id is not None:
                    edges[child_id].append((parent_id, "parent", marriage_id))
        if "child" in relationships:
            for parent_id in (
                marriage.get("husband_person_id"),
                marriage.get("wife_person_id"),
            ):
                if parent_id in frontier_set and child_id is not None:
                    edges[parent_id].append((child_id, "child", marriage_id))
    if "spouse" in relationships:
        for marriage in own_marriages:
            husband = marriage.get("husband_person_id")
            wife = marriage.get("wife_person_id")
            marriage_id = marriage.get("marriage_id")
            if husband != wife:
                if husband in frontier_set and wife is not None:
                    edges[husband].append((wife, "spouse", marriage_id))
                if wife in frontier_set and husband is not None:
                    edges[wife].append((husband, "spouse", marriage_id))
    return edges


def _specific_relationship(base: str, target: Mapping[str, JsonValue]) -> str:
    gender_value = target.get("gender_code")
    gender = str(gender_value).strip().lower() if gender_value is not None else ""
    male = gender in {"0", "m", "male"}
    female = gender in {"1", "f", "female"}
    if base == "parent":
        return "father" if male else "mother" if female else "parent"
    if base == "child":
        return "son" if male else "daughter" if female else "child"
    if base == "spouse":
        return "husband" if male else "wife" if female else "spouse"
    return base


def get_tree(
    source: DatabaseSource,
    dataset_id: Any,
    person_id: Any,
    *,
    direction: str = "ancestors",
    max_depth: int = 4,
) -> JsonObject | None:
    """Traverse ancestors or descendants breadth-first without following spouses."""

    if direction not in {"ancestors", "descendants"}:
        raise ValueError("direction must be 'ancestors' or 'descendants'")
    max_depth = max(0, min(int(max_depth), 100))
    wanted_edge = "parent" if direction == "ancestors" else "child"
    with _connection(source) as connection:
        people = _compact_people(connection, dataset_id, [person_id])
        root_id = _matching_person_id(people, person_id)
        if root_id is None:
            return None
        visited = {root_id}
        missing: set[JsonValue] = set()
        frontier = [root_id]
        traversed: list[JsonObject] = []
        tree_links: list[JsonObject] = []
        generations: defaultdict[int, list[JsonObject]] = defaultdict(list)
        for depth in range(max_depth):
            if not frontier:
                break
            edges = _frontier_edges(connection, dataset_id, frontier, relationships={wanted_edge})
            targets = [target for current in frontier for target, _, _ in edges.get(current, [])]
            unfetched = [
                target for target in targets if target not in people and target not in missing
            ]
            fetched = _compact_people(connection, dataset_id, unfetched)
            people.update(fetched)
            missing.update(set(unfetched) - set(fetched))
            next_frontier: list[JsonValue] = []
            for current in frontier:
                for target, edge, marriage_id in edges.get(current, []):
                    if target not in people:
                        continue
                    relationship = _specific_relationship(edge, people[target])
                    tree_links.append(
                        {
                            "from_person_id": current,
                            "to_person_id": target,
                            "relationship": relationship,
                            "marriage_id": marriage_id,
                        }
                    )
                    if target in visited:
                        continue
                    visited.add(target)
                    item = _person_reference(people[target])
                    item["depth"] = depth + 1
                    item["relationship"] = relationship
                    traversed.append(item)
                    generations[depth + 1].append(item)
                    next_frontier.append(target)
            frontier = next_frontier
        return {
            "root": _person_reference(people[root_id]),
            "direction": direction,
            "max_depth": max_depth,
            "people": traversed,
            "generations": [
                {"depth": depth, "people": generations[depth]} for depth in sorted(generations)
            ],
            "links": tree_links,
        }


def get_ancestors(
    source: DatabaseSource, dataset_id: Any, person_id: Any, *, max_depth: int = 4
) -> JsonObject | None:
    return get_tree(source, dataset_id, person_id, direction="ancestors", max_depth=max_depth)


def get_descendants(
    source: DatabaseSource, dataset_id: Any, person_id: Any, *, max_depth: int = 4
) -> JsonObject | None:
    return get_tree(source, dataset_id, person_id, direction="descendants", max_depth=max_depth)


def shortest_relationship_path(
    source: DatabaseSource,
    dataset_id: Any,
    from_person_id: Any,
    to_person_id: Any,
) -> JsonObject:
    """Find and explain the shortest parent/child/spouse path using BFS."""

    with _connection(source) as connection:
        people = _compact_people(connection, dataset_id, [from_person_id, to_person_id])
        start = _matching_person_id(people, from_person_id)
        goal = _matching_person_id(people, to_person_id)
        if start is None or goal is None:
            missing = "from" if start is None else "to"
            return {"found": False, "reason": f"{missing} person was not found", "steps": []}
        if start == goal:
            return {
                "found": True,
                "length": 0,
                "people": [_person_reference(people[start])],
                "steps": [],
                "explanation": "Both identifiers refer to the same person.",
            }

        previous: dict[JsonValue, tuple[JsonValue, str, JsonValue | None]] = {}
        visited = {start}
        missing: set[JsonValue] = set()
        frontier = [start]
        while frontier and goal not in visited:
            edges = _frontier_edges(
                connection,
                dataset_id,
                frontier,
                relationships={"parent", "child", "spouse"},
            )
            targets = [target for current in frontier for target, _, _ in edges.get(current, [])]
            unfetched = [
                target for target in targets if target not in people and target not in missing
            ]
            fetched = _compact_people(connection, dataset_id, unfetched)
            people.update(fetched)
            missing.update(set(unfetched) - set(fetched))
            next_frontier: list[JsonValue] = []
            for current in frontier:
                for target, relationship, marriage_id in edges.get(current, []):
                    if target in visited or target not in people:
                        continue
                    visited.add(target)
                    previous[target] = (current, relationship, marriage_id)
                    next_frontier.append(target)
                    if target == goal:
                        break
                if goal in visited:
                    break
            frontier = next_frontier
        if goal not in visited:
            return {
                "found": False,
                "reason": "No relationship path was found in this dataset.",
                "steps": [],
            }

        path = [goal]
        while path[-1] != start:
            path.append(previous[path[-1]][0])
        path.reverse()
        steps: list[JsonObject] = []
        explanations = []
        explained_path = [_person_reference(people[start])]
        for current, target in pairwise(path):
            _, base_relationship, marriage_id = previous[target]
            relationship = _specific_relationship(base_relationship, people[target])
            from_name = _display_name(people[current])
            to_name = _display_name(people[target])
            description = f"{to_name} is the {relationship} of {from_name}."
            steps.append(
                {
                    "from_person_id": current,
                    "to_person_id": target,
                    "relationship": relationship,
                    "marriage_id": marriage_id,
                    "description": description,
                }
            )
            path_person = _person_reference(people[target])
            path_person["relationship"] = relationship
            explained_path.append(path_person)
            explanations.append(description)
        return {
            "found": True,
            "length": len(steps),
            "people": [_person_reference(people[key]) for key in path],
            "path": explained_path,
            "steps": steps,
            "explanation": " ".join(explanations),
        }


find_relationship = shortest_relationship_path
