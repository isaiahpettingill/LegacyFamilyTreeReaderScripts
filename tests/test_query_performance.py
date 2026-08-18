from __future__ import annotations

import sqlite3
from pathlib import Path

from legacy_family_tree_reader.queries import (
    get_ancestors,
    get_descendants,
    get_family,
    shortest_relationship_path,
)


def test_family_tree_and_path_queries_do_not_materialize_unrelated_people(
    merged_db: Path,
) -> None:
    with sqlite3.connect(merged_db) as connection:
        connection.executemany(
            """INSERT INTO individuals
               (dataset_id, legacy_id, individual_id, given_name, surname, gender)
               VALUES (1, ?, ?, 'Unrelated', 'Person', 0)""",
            ((person_id, person_id) for person_id in range(10_000, 12_000)),
        )
        statements: list[str] = []
        connection.set_trace_callback(statements.append)

        family = get_family(connection, 1, 3)
        ancestors = get_ancestors(connection, 1, 3, max_depth=3)
        descendants = get_descendants(connection, 1, 1, max_depth=3)
        path = shortest_relationship_path(connection, 1, 2, 5)

    assert family is not None
    assert ancestors is not None
    assert descendants is not None
    assert path["found"] is True

    person_selects = [statement for statement in statements if 'FROM "individuals"' in statement]
    assert person_selects
    assert all('"individual_id" IN (' in statement for statement in person_selects)
    assert all(
        "*" not in statement.split(' FROM "individuals"', maxsplit=1)[0]
        for statement in person_selects
    )
    assert all(
        "10000" not in statement and "11999" not in statement for statement in person_selects
    )

    marriage_selects = [statement for statement in statements if 'FROM "marriages"' in statement]
    assert marriage_selects
    assert all(" OR " not in statement.upper() for statement in marriage_selects)


def test_descendant_tree_keeps_pedigree_collapse_links_but_visits_person_once(
    merged_db: Path,
) -> None:
    with sqlite3.connect(merged_db) as connection:
        connection.execute(
            """INSERT INTO individuals
               (dataset_id, legacy_id, individual_id, given_name, surname, gender)
               VALUES (1, 700, 7, 'River', 'Branch', 1)"""
        )
        connection.execute(
            """INSERT INTO marriages
               (dataset_id, legacy_id, marriage_id,
                husband_individual_id, wife_individual_id)
               VALUES (1, 12, 12, 3, 6)"""
        )
        connection.execute(
            """INSERT INTO children
               (dataset_id, child_id, marriage_id, individual_id, display_order)
               VALUES (1, 105, 12, 7, 1)"""
        )

    tree = get_descendants(merged_db, 1, 1, max_depth=2)

    assert tree is not None
    assert [person["person_id"] for person in tree["people"]].count(7) == 1
    collapse_links = [link for link in tree["links"] if link["to_person_id"] == 7]
    assert collapse_links == [
        {
            "from_person_id": 3,
            "to_person_id": 7,
            "relationship": "daughter",
            "marriage_id": 12,
        },
        {
            "from_person_id": 6,
            "to_person_id": 7,
            "relationship": "daughter",
            "marriage_id": 12,
        },
    ]
