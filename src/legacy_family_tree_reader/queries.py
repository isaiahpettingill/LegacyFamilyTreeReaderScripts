"""Read-only queries for the descriptive Legacy Family Tree SQLite database."""

from __future__ import annotations

import sqlite3
from collections import defaultdict, deque
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
        parameters.append(limit)
        surname_column = _first_column(people_columns, "surname")
        given_column = _first_column(people_columns, "given_names", "given_name")
        order_parts = [
            f"COALESCE(p.{_quote_identifier(column)}, '')"
            for column in (surname_column, given_column)
            if column is not None
        ]
        order_parts.append(f"p.{_quote_identifier(person_id_column)}")
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


def _family_data(
    connection: sqlite3.Connection, dataset_id: Any
) -> tuple[
    dict[JsonValue, JsonObject],
    list[JsonObject],
    list[JsonObject],
]:
    people_table, _, _ = _person_source(connection)
    people_rows = [
        _normalize_person(row) for row in _dataset_rows(connection, people_table, dataset_id)
    ]
    people = _id_map(people_rows, "person_id")
    marriages = _dataset_rows(connection, "marriages", dataset_id)
    for marriage in marriages:
        _add_alias(marriage, "husband_person_id", "husband_individual_id")
        _add_alias(marriage, "wife_person_id", "wife_individual_id")
    link_table = (
        "parent_child_links" if _table_exists(connection, "parent_child_links") else "children"
    )
    links = _dataset_rows(connection, link_table, dataset_id)
    for link in links:
        _add_alias(link, "parent_marriage_id", "marriage_id")
        _add_alias(link, "child_person_id", "individual_id", "child_individual_id")
        _add_alias(link, "child_order", "display_order")
    return people, marriages, links


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


def get_family(source: DatabaseSource, dataset_id: Any, person_id: Any) -> JsonObject | None:
    """Return parents, spouses, children, and siblings for one person."""

    with _connection(source) as connection:
        people, marriages, links = _family_data(connection, dataset_id)
        person = people.get(person_id)
        if person is None:
            # URL values are strings while SQLite identifiers are often integers.
            person = next((row for key, row in people.items() if str(key) == str(person_id)), None)
        if person is None:
            return None
        actual_id = person.get("person_id")
        marriage_by_id = _id_map(marriages, "marriage_id")
        own_marriages = [
            marriage
            for marriage in marriages
            if actual_id in (marriage.get("husband_person_id"), marriage.get("wife_person_id"))
        ]
        parent_links = [link for link in links if link.get("child_person_id") == actual_id]
        parent_marriage_ids = {link.get("parent_marriage_id") for link in parent_links}

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
        own_marriage_ids = {marriage.get("marriage_id") for marriage in own_marriages}
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
        for link in links:
            if link.get("parent_marriage_id") in own_marriage_ids:
                child_id = link.get("child_person_id")
                if child_id in people:
                    children.append(
                        _with_relationship(
                            people[child_id], "child", link.get("parent_marriage_id")
                        )
                    )

        siblings: list[JsonObject] = []
        for link in links:
            if (
                link.get("parent_marriage_id") in parent_marriage_ids
                and link.get("child_person_id") != actual_id
                and link.get("child_person_id") in people
            ):
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


def _graph(
    people: dict[JsonValue, JsonObject],
    marriages: list[JsonObject],
    links: list[JsonObject],
    *,
    include_spouses: bool,
) -> dict[JsonValue, list[tuple[JsonValue, str, JsonValue | None]]]:
    graph: defaultdict[JsonValue, list[tuple[JsonValue, str, JsonValue | None]]] = defaultdict(list)
    marriage_by_id = _id_map(marriages, "marriage_id")
    for link in links:
        marriage_id = link.get("parent_marriage_id")
        child_id = link.get("child_person_id")
        marriage = marriage_by_id.get(marriage_id)
        if child_id not in people or not marriage:
            continue
        for parent_id in (
            marriage.get("husband_person_id"),
            marriage.get("wife_person_id"),
        ):
            if parent_id in people:
                graph[child_id].append((parent_id, "parent", marriage_id))
                graph[parent_id].append((child_id, "child", marriage_id))
    if include_spouses:
        for marriage in marriages:
            husband = marriage.get("husband_person_id")
            wife = marriage.get("wife_person_id")
            marriage_id = marriage.get("marriage_id")
            if husband in people and wife in people and husband != wife:
                graph[husband].append((wife, "spouse", marriage_id))
                graph[wife].append((husband, "spouse", marriage_id))
    return graph


def _resolve_person_id(people: Mapping[JsonValue, JsonObject], person_id: Any) -> JsonValue | None:
    if person_id in people:
        return person_id
    return next((key for key in people if str(key) == str(person_id)), None)


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
        people, marriages, links = _family_data(connection, dataset_id)
        root_id = _resolve_person_id(people, person_id)
        if root_id is None:
            return None
        graph = _graph(people, marriages, links, include_spouses=False)
        queue = deque([(root_id, 0)])
        visited = {root_id}
        traversed: list[JsonObject] = []
        tree_links: list[JsonObject] = []
        generations: defaultdict[int, list[JsonObject]] = defaultdict(list)
        while queue:
            current, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for target, edge, marriage_id in graph.get(current, []):
                if edge != wanted_edge:
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
                queue.append((target, depth + 1))
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
        people, marriages, links = _family_data(connection, dataset_id)
        start = _resolve_person_id(people, from_person_id)
        goal = _resolve_person_id(people, to_person_id)
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

        graph = _graph(people, marriages, links, include_spouses=True)
        queue = deque([start])
        previous: dict[JsonValue, tuple[JsonValue, str, JsonValue | None]] = {}
        visited = {start}
        while queue and goal not in visited:
            current = queue.popleft()
            for target, relationship, marriage_id in graph.get(current, []):
                if target in visited:
                    continue
                visited.add(target)
                previous[target] = (current, relationship, marriage_id)
                queue.append(target)
                if target == goal:
                    break
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
