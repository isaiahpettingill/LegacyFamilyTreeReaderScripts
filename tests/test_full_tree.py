from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from legacy_family_tree_reader.queries import get_descendant_family_tree
from legacy_family_tree_reader.server import create_app


@pytest.fixture
def descendant_family_db(merged_db: Path) -> Path:
    with sqlite3.connect(merged_db) as connection:
        connection.execute(
            "UPDATE individuals SET given_name='Douglas' WHERE dataset_id=1 AND individual_id=1"
        )
        connection.execute(
            "UPDATE individuals SET given_name='Martha' WHERE dataset_id=1 AND individual_id=2"
        )
        connection.executemany(
            """INSERT INTO individuals
               (dataset_id, legacy_id, individual_id, given_name, surname, gender, living, private)
               VALUES (1, ?, ?, ?, 'Example', ?, 0, ?)""",
            (
                (700, 7, "Avery", 1, 1),
                (800, 8, "Quinn", 0, 0),
                (900, 9, "Outside", 0, 0),
                (1000, 10, "SpouseOnlyChild", 1, 0),
                (1100, 11, "Taylor", 0, 0),
                (1200, 12, "OtherChild", 1, 0),
                (1300, 13, "Robin", 0, 0),
                (1400, 14, "Sky", 1, 0),
                (1500, 15, "Lake", 0, 0),
                (1600, 16, "Gray", 1, 0),
                (1700, 17, "CyclePartner", 1, 0),
            ),
        )
        connection.executemany(
            """INSERT INTO marriages
               (dataset_id, legacy_id, marriage_id,
                husband_individual_id, wife_individual_id, private)
               VALUES (1, ?, ?, ?, ?, ?)""",
            (
                (12, 12, 3, 7, 1),
                (13, 13, 7, 9, 0),
                (14, 14, 4, 11, 0),
                (15, 15, 6, 13, 0),
                (16, 16, 5, 14, 0),
                (17, 17, 8, None, 0),
                (18, 18, 15, 17, 0),
            ),
        )
        connection.executemany(
            """INSERT INTO children
               (dataset_id, child_id, marriage_id, individual_id, display_order)
               VALUES (1, ?, ?, ?, ?)""",
            (
                (105, 12, 8, 1),
                (106, 13, 10, 1),
                (107, 14, 12, 1),
                (108, 15, 14, 1),
                (109, 16, 15, 1),
                (110, 17, 16, 1),
                (111, 18, 3, 1),
            ),
        )
    return merged_db


def test_full_descendant_family_tree_includes_spouses_but_not_their_other_families(
    descendant_family_db: Path,
) -> None:
    tree = get_descendant_family_tree(descendant_family_db, 1, 1, 2)

    assert tree is not None
    assert tree == get_descendant_family_tree(descendant_family_db, 1, 1, 2)
    assert tree["status"] == "ok"
    assert [root["display_name"] for root in tree["roots"]] == ["Douglas North", "Martha West"]
    people = {person["person_id"]: person for person in tree["people"]}
    assert set(people) == {1, 2, 3, 4, 5, 6, 7, 8, 13, 14, 15, 16, 17}
    assert {person_id for person_id, person in people.items() if person["role"] == "spouse"} == {
        4,
        7,
        13,
        17,
    }
    assert people[14]["role"] == "descendant"
    assert people[6]["private_flag"] == 1
    assert people[7]["private_flag"] == 1

    families = {family["marriage_id"]: family for family in tree["families"]}
    assert [family["marriage_id"] for family in tree["families"]] == [10, 11, 12, 15, 16, 17, 18]
    assert set(families) == {10, 11, 12, 15, 16, 17, 18}
    assert families[10]["root_union"] is True
    assert families[12]["private_flag"] == 1
    assert families[16]["partner_person_ids"] == [5, 14]
    assert families[17]["partner_person_ids"] == [8]
    assert families[17]["wife"] is None
    assert families[17]["child_ids"] == [16]
    assert 13 not in families
    assert 14 not in families

    cycle_links = [link for link in tree["links"] if link["parent_marriage_id"] == 18]
    assert len(cycle_links) == 1
    assert cycle_links[0]["parent_person_ids"] == [15, 17]
    assert cycle_links[0]["child_person_id"] == 3
    assert cycle_links[0]["depth"] == 4
    assert [parent["person_id"] for parent in cycle_links[0]["parent_references"]] == [15, 17]
    assert cycle_links[0]["child"]["person_id"] == 3
    assert tree["counts"] == {
        "roots": 2,
        "descendants": 7,
        "spouses": 4,
        "people": 13,
        "families": 7,
        "links": 8,
        "generations": 4,
    }


def test_full_tree_depth_is_bounded_but_keeps_terminal_descendant_spouses(
    descendant_family_db: Path,
) -> None:
    tree = get_descendant_family_tree(descendant_family_db, 1, 1, 2, max_depth=1)

    assert tree is not None
    people = {person["person_id"]: person for person in tree["people"]}
    assert set(people) == {1, 2, 3, 4, 6, 7, 13}
    assert {person_id for person_id, person in people.items() if person["role"] == "spouse"} == {
        4,
        7,
        13,
    }
    assert {family["marriage_id"] for family in tree["families"]} == {10, 11, 12, 15}
    assert all(family["child_ids"] == [] for family in tree["families"] if family["depth"] == 1)
    assert tree["truncated"] is True


def test_full_tree_missing_roots_and_no_shared_union_are_distinct(
    descendant_family_db: Path,
) -> None:
    assert get_descendant_family_tree(descendant_family_db, 1, 1, 9999) is None

    tree = get_descendant_family_tree(descendant_family_db, 1, 1, 4)
    assert tree is not None
    assert tree["status"] == "no_shared_union"
    assert tree["families"] == []
    assert tree["links"] == []
    assert tree["counts"]["people"] == 2


def test_full_tree_api_validation_head_auth_and_status_mapping(
    descendant_family_db: Path,
) -> None:
    with TestClient(create_app(descendant_family_db)) as client:
        response = client.get(
            "/api/full-tree",
            params={"dataset": 1, "first": 1, "second": 2, "generations": 1},
        )
        assert response.status_code == 200
        assert response.json()["max_depth"] == 1

        capped = client.get(
            "/api/full-tree",
            params={"dataset": 1, "first": 1, "second": 2, "max_depth": 999},
        )
        assert capped.status_code == 200
        assert capped.json()["max_depth"] == 100

        head = client.head("/api/full-tree", params={"dataset": 1, "first": 1, "second": 2})
        assert head.status_code == 200
        assert head.content == b""
        assert client.get("/api/full-tree", params={"dataset": 1}).status_code == 400
        assert (
            client.get(
                "/api/full-tree",
                params={"dataset": 1, "first": 1, "second": 2, "generations": "many"},
            ).status_code
            == 400
        )
        missing = client.get("/api/full-tree", params={"dataset": 1, "first": 1, "second": 9999})
        assert missing.status_code == 404
        assert missing.json() == {"error": "One or both root people were not found"}
        no_union = client.get("/api/full-tree", params={"dataset": 1, "first": 1, "second": 4})
        assert no_union.status_code == 200
        assert no_union.json()["status"] == "no_shared_union"

    with TestClient(
        create_app(descendant_family_db, password="family", session_secret="secret")
    ) as protected_client:
        assert (
            protected_client.get(
                "/api/full-tree", params={"dataset": 1, "first": 1, "second": 2}
            ).status_code
            == 401
        )


def test_full_tree_uses_targeted_indexable_queries(
    descendant_family_db: Path,
) -> None:
    with sqlite3.connect(descendant_family_db) as connection:
        connection.executemany(
            """INSERT INTO individuals
               (dataset_id, legacy_id, individual_id, given_name, surname, gender)
               VALUES (1, ?, ?, 'Unrelated', 'Bulk', 0)""",
            ((person_id, person_id) for person_id in range(20_000, 22_000)),
        )
        statements: list[str] = []
        connection.set_trace_callback(statements.append)
        tree = get_descendant_family_tree(connection, 1, 1, 2, max_depth=2)

    assert tree is not None
    person_selects = [statement for statement in statements if 'FROM "individuals"' in statement]
    assert person_selects
    assert all('"individual_id" IN (' in statement for statement in person_selects)
    assert all(
        "*" not in statement.split(' FROM "individuals"', maxsplit=1)[0]
        for statement in person_selects
    )
    assert all(
        "20000" not in statement and "21999" not in statement for statement in person_selects
    )

    marriage_selects = [statement for statement in statements if 'FROM "marriages"' in statement]
    child_selects = [statement for statement in statements if 'FROM "children"' in statement]
    assert marriage_selects and child_selects
    assert all(" OR " not in statement.upper() for statement in marriage_selects)
    assert all(" IN (" in statement.upper() for statement in child_selects)
