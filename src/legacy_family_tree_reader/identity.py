"""Explicit cross-dataset identity reconciliation.

Identity groups are deliberately separate from imported records.  A person can
belong to one group, and linking two existing groups merges them atomically.
Suggestions are read-only and are never applied automatically.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class IdentityError(RuntimeError):
    """Raised when an identity operation cannot be completed safely."""


def _connect(database_path: str | Path) -> sqlite3.Connection:
    path = Path(database_path).expanduser().resolve(strict=True)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    return connection


def ensure_identity_schema(connection: sqlite3.Connection) -> None:
    """Create the reconciliation tables on demand."""

    connection.execute("""
        CREATE TABLE IF NOT EXISTS identity_groups (
            id INTEGER PRIMARY KEY,
            created_at TEXT NOT NULL
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS identity_members (
            group_id INTEGER NOT NULL REFERENCES identity_groups(id) ON DELETE CASCADE,
            dataset_id INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
            person_id INTEGER NOT NULL,
            added_at TEXT NOT NULL,
            PRIMARY KEY (dataset_id, person_id)
        )
    """)
    connection.execute(
        "CREATE INDEX IF NOT EXISTS identity_members_group_idx ON identity_members(group_id)"
    )


def _person_table(connection: sqlite3.Connection) -> tuple[str, str]:
    for table, person_id in (("individuals", "individual_id"), ("people", "person_id")):
        columns = {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
        if {"dataset_id", person_id} <= columns:
            return table, person_id
    raise IdentityError("database does not contain a supported people table")


def _require_person(connection: sqlite3.Connection, dataset_id: int, person_id: int) -> None:
    table, id_column = _person_table(connection)
    if (
        connection.execute(
            f'SELECT 1 FROM "{table}" WHERE dataset_id=? AND "{id_column}"=? LIMIT 1',
            (dataset_id, person_id),
        ).fetchone()
        is None
    ):
        raise IdentityError(f"person {person_id} was not found in dataset {dataset_id}")


def _group(connection: sqlite3.Connection, group_id: int) -> dict[str, Any]:
    group_row = connection.execute(
        "SELECT id, created_at FROM identity_groups WHERE id=?", (group_id,)
    ).fetchone()
    if group_row is None:
        raise IdentityError(f"identity group {group_id} was not found")
    members = [
        {
            "dataset_id": row[0],
            "person_id": row[1],
            "added_at": row[2],
        }
        for row in connection.execute(
            """SELECT dataset_id, person_id, added_at
               FROM identity_members WHERE group_id=?
               ORDER BY dataset_id, person_id""",
            (group_id,),
        )
    ]
    return {"group_id": group_row[0], "created_at": group_row[1], "members": members}


def link_people(
    database_path: str | Path,
    dataset_a: int,
    person_a: int,
    dataset_b: int,
    person_b: int,
) -> dict[str, Any]:
    """Link two people, merging their identity groups when necessary."""

    if dataset_a == dataset_b:
        raise IdentityError("identity links must connect two different datasets")
    now = datetime.now(UTC).isoformat()
    connection = _connect(database_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        ensure_identity_schema(connection)
        _require_person(connection, dataset_a, person_a)
        _require_person(connection, dataset_b, person_b)
        member_a = connection.execute(
            "SELECT group_id FROM identity_members WHERE dataset_id=? AND person_id=?",
            (dataset_a, person_a),
        ).fetchone()
        member_b = connection.execute(
            "SELECT group_id FROM identity_members WHERE dataset_id=? AND person_id=?",
            (dataset_b, person_b),
        ).fetchone()

        group_a = int(member_a[0]) if member_a else None
        group_b = int(member_b[0]) if member_b else None
        if group_a is None and group_b is None:
            group_id = int(
                connection.execute(
                    "INSERT INTO identity_groups(created_at) VALUES (?)", (now,)
                ).lastrowid
            )
            connection.executemany(
                """INSERT INTO identity_members
                   (group_id, dataset_id, person_id, added_at) VALUES (?, ?, ?, ?)""",
                (
                    (group_id, dataset_a, person_a, now),
                    (group_id, dataset_b, person_b, now),
                ),
            )
        elif group_a is None:
            group_id = group_b
            connection.execute(
                """INSERT INTO identity_members
                   (group_id, dataset_id, person_id, added_at) VALUES (?, ?, ?, ?)""",
                (group_id, dataset_a, person_a, now),
            )
        elif group_b is None:
            group_id = group_a
            connection.execute(
                """INSERT INTO identity_members
                   (group_id, dataset_id, person_id, added_at) VALUES (?, ?, ?, ?)""",
                (group_id, dataset_b, person_b, now),
            )
        elif group_a == group_b:
            group_id = group_a
        else:
            group_id = min(group_a, group_b)
            obsolete_group = max(group_a, group_b)
            connection.execute(
                "UPDATE identity_members SET group_id=? WHERE group_id=?",
                (group_id, obsolete_group),
            )
            connection.execute("DELETE FROM identity_groups WHERE id=?", (obsolete_group,))

        result = _group(connection, group_id)
        connection.commit()
        return result
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def list_identity_groups(database_path: str | Path) -> list[dict[str, Any]]:
    """List all explicit identity groups and their members."""

    connection = _connect(database_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        ensure_identity_schema(connection)
        group_ids = [
            row[0] for row in connection.execute("SELECT id FROM identity_groups ORDER BY id")
        ]
        result = [_group(connection, group_id) for group_id in group_ids]
        connection.commit()
        return result
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def _normal_text(value: object) -> str:
    if value is None:
        return ""
    decomposed = unicodedata.normalize("NFKD", str(value).casefold())
    return "".join(
        character
        for character in decomposed
        if character.isalnum() and not unicodedata.combining(character)
    )


def _date_key(sort_date: object, display_date: object) -> str:
    raw_sort_key = "" if sort_date is None else str(sort_date).strip()
    sort_key = _normal_text(sort_date)
    if raw_sort_key not in {"", "0", "-99999999", "99999999"} and set(sort_key) != {"0"}:
        return f"sort:{sort_key}"
    display_key = _normal_text(display_date)
    if not display_key or not re.search(r"\d{3,4}", display_key):
        return ""
    return f"date:{display_key}"


def _candidate_people(
    connection: sqlite3.Connection, dataset_ids: Iterable[int] | None
) -> list[dict[str, Any]]:
    columns = {row[1] for row in connection.execute('PRAGMA table_info("individuals")')}
    required = {"dataset_id", "individual_id", "given_name", "surname"}
    if not required <= columns:
        raise IdentityError("database does not contain canonical individual records")
    optional = (
        "birth_sort_date",
        "birth_date",
        "death_sort_date",
        "death_date",
    )
    selected = ["dataset_id", "individual_id", "given_name", "surname"]
    selected.extend(column for column in optional if column in columns)
    selected.extend(f"NULL AS {column}" for column in optional if column not in columns)
    parameters: list[int] = []
    where = ""
    if dataset_ids is not None:
        parameters = list(dict.fromkeys(dataset_ids))
        if not parameters:
            return []
        where = f" WHERE dataset_id IN ({', '.join('?' for _ in parameters)})"
    cursor = connection.execute(f"SELECT {', '.join(selected)} FROM individuals{where}", parameters)
    names = [item[0] for item in cursor.description or ()]
    return [dict(zip(names, row, strict=True)) for row in cursor]


def suggest_links(
    database_path: str | Path,
    dataset_ids: Iterable[int] | None = None,
    *,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Suggest conservative cross-dataset matches without linking them.

    Candidates need an exact normalized given-name and surname match, plus an
    exact birth or death key.  Conflicting known vital dates reject a match.
    """

    limit = max(1, min(int(limit), 1000))
    connection = _connect(database_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        ensure_identity_schema(connection)
        grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
        for person in _candidate_people(connection, dataset_ids):
            given = _normal_text(person["given_name"])
            surname = _normal_text(person["surname"])
            if given and surname:
                grouped[f"{given}|{surname}"].append(person)
        memberships = {
            (row[0], row[1]): row[2]
            for row in connection.execute(
                "SELECT dataset_id, person_id, group_id FROM identity_members"
            )
        }
        suggestions: list[dict[str, Any]] = []
        for people in grouped.values():
            people.sort(key=lambda item: (str(item["dataset_id"]), str(item["individual_id"])))
            for index, left in enumerate(people):
                for right in people[index + 1 :]:
                    if left["dataset_id"] == right["dataset_id"]:
                        continue
                    left_group = memberships.get((left["dataset_id"], left["individual_id"]))
                    right_group = memberships.get((right["dataset_id"], right["individual_id"]))
                    if left_group is not None and left_group == right_group:
                        continue
                    left_birth = _date_key(left["birth_sort_date"], left["birth_date"])
                    right_birth = _date_key(right["birth_sort_date"], right["birth_date"])
                    left_death = _date_key(left["death_sort_date"], left["death_date"])
                    right_death = _date_key(right["death_sort_date"], right["death_date"])
                    if left_birth and right_birth and left_birth != right_birth:
                        continue
                    if left_death and right_death and left_death != right_death:
                        continue
                    reasons = []
                    if left_birth and left_birth == right_birth:
                        reasons.append("birth")
                    if left_death and left_death == right_death:
                        reasons.append("death")
                    if not reasons:
                        continue
                    suggestions.append(
                        {
                            "person_a": {
                                "dataset_id": left["dataset_id"],
                                "person_id": left["individual_id"],
                                "given_name": left["given_name"],
                                "surname": left["surname"],
                            },
                            "person_b": {
                                "dataset_id": right["dataset_id"],
                                "person_id": right["individual_id"],
                                "given_name": right["given_name"],
                                "surname": right["surname"],
                            },
                            "matched_on": ["normalized_name", *reasons],
                        }
                    )
                    if len(suggestions) >= limit:
                        connection.commit()
                        return suggestions
        connection.commit()
        return suggestions
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


__all__ = [
    "IdentityError",
    "ensure_identity_schema",
    "link_people",
    "list_identity_groups",
    "suggest_links",
]
