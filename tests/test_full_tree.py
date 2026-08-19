from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from legacy_family_tree_reader.queries import get_ancestor_family_tree
from legacy_family_tree_reader.server import create_app


@pytest.fixture
def ancestor_family_db(merged_db: Path) -> Path:
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
                (700, 7, "Arthur", 0, 1),
                (800, 8, "Beatrice", 1, 0),
                (900, 9, "Charles", 0, 0),
                (1000, 10, "Dorothy", 1, 0),
                (1100, 11, "Edwin", 0, 0),
                (1200, 12, "Florence", 1, 0),
                (1300, 13, "George", 0, 0),
                (1400, 14, "Helen", 1, 0),
                (1500, 15, "Isaac", 0, 0),
                (1600, 16, "Julia", 1, 0),
                (1700, 17, "Alternate", 1, 0),
                (1800, 18, "Sibling", 1, 0),
                (1900, 19, "Aunt", 1, 0),
                (2000, 20, "Cycle", 0, 0),
                (2100, 21, "CycleSpouse", 1, 0),
            ),
        )
        connection.executemany(
            """INSERT INTO marriages
               (dataset_id, legacy_id, marriage_id,
                husband_individual_id, wife_individual_id, private)
               VALUES (1, ?, ?, ?, ?, ?)""",
            (
                (20, 20, 7, 8, 0),
                (21, 21, 9, 10, 0),
                (22, 22, 11, 12, 0),
                (23, 23, 13, 14, 0),
                (24, 24, 15, 16, 0),
                (25, 25, 20, 21, 0),
                (26, 26, 7, 17, 0),
                (27, 27, 1, 17, 0),
            ),
        )
        connection.executemany(
            """INSERT INTO children
               (dataset_id, child_id, marriage_id, individual_id, display_order)
               VALUES (1, ?, ?, ?, ?)""",
            (
                (200, 20, 1, 1),
                (201, 20, 18, 2),
                (202, 21, 2, 1),
                (203, 22, 7, 1),
                (204, 22, 19, 2),
                (205, 23, 8, 1),
                (206, 24, 9, 1),
                (207, 25, 11, 1),
            ),
        )
    return merged_db


def test_ancestor_tree_builds_root_parent_and_grandparent_couples(
    ancestor_family_db: Path,
) -> None:
    tree = get_ancestor_family_tree(ancestor_family_db, 1, 1, 2, max_depth=2)

    assert tree is not None
    assert tree == get_ancestor_family_tree(ancestor_family_db, 1, 1, 2, max_depth=2)
    assert tree["status"] == "ok"
    assert [root["display_name"] for root in tree["roots"]] == [
        "Douglas North",
        "Martha West",
    ]

    couples = {couple["marriage_id"]: couple for couple in tree["couples"]}
    assert [couple["marriage_id"] for couple in tree["couples"]] == [10, 20, 21, 22, 23, 24]
    assert couples[10]["root_couple"] is True
    assert couples[10]["depth"] == 0
    assert couples[20]["depth"] == 1
    assert couples[22]["depth"] == 2
    assert couples[20]["partner_person_ids"] == [7, 8]
    assert couples[10]["child_ids"] == [3, 6]
    assert [child["person_id"] for child in couples[20]["children"]] == [1, 18]
    assert couples[22]["child_ids"] == [7, 19]

    assert tree["links"] == [
        {"child_person_id": 1, "parent_couple_id": 20, "depth": 1},
        {"child_person_id": 2, "parent_couple_id": 21, "depth": 1},
        {"child_person_id": 7, "parent_couple_id": 22, "depth": 2},
        {"child_person_id": 8, "parent_couple_id": 23, "depth": 2},
        {"child_person_id": 9, "parent_couple_id": 24, "depth": 2},
    ]
    assert tree["has_parents"] == [1, 2, 7, 8, 9, 11]
    assert tree["truncated"] is True
    assert tree["counts"] == {
        "people": 17,
        "couples": 6,
        "links": 5,
        "generations": 3,
    }

    people = {person["person_id"]: person for person in tree["people"]}
    assert set(people) == {1, 2, 3, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19}
    assert people[7]["private_flag"] == 1
    assert people[6]["private_flag"] == 1
    assert people[11]["depth"] == 2
    assert "depth" not in people[18]


def test_children_menus_and_alternative_spouses_include_references_but_do_not_traverse(
    ancestor_family_db: Path,
) -> None:
    tree = get_ancestor_family_tree(ancestor_family_db, 1, 1, 2, max_depth=1)

    assert tree is not None
    couples = {couple["marriage_id"]: couple for couple in tree["couples"]}
    root_alternatives = couples[10]["alternative_spouses"]
    assert [(item["partner_person_id"], item["marriage_id"]) for item in root_alternatives] == [
        (1, 27)
    ]
    assert root_alternatives[0]["spouse"]["person_id"] == 17
    assert 10 not in {item["marriage_id"] for item in root_alternatives}

    parent_alternatives = couples[20]["alternative_spouses"]
    assert [(item["partner_person_id"], item["marriage_id"]) for item in parent_alternatives] == [
        (7, 26)
    ]
    assert 20 not in {item["marriage_id"] for item in parent_alternatives}
    assert {child["person_id"] for child in couples[10]["children"]} == {3, 6}
    assert {child["person_id"] for child in couples[20]["children"]} == {1, 18}
    assert 17 in {person["person_id"] for person in tree["people"]}
    assert 18 in {person["person_id"] for person in tree["people"]}
    assert 26 not in couples
    assert 27 not in couples


def test_depth_zero_and_terminal_generation_report_older_ancestors(
    ancestor_family_db: Path,
) -> None:
    tree = get_ancestor_family_tree(ancestor_family_db, 1, 1, 2, max_depth=0)

    assert tree is not None
    assert [couple["marriage_id"] for couple in tree["couples"]] == [10]
    assert tree["links"] == []
    assert tree["has_parents"] == [1, 2]
    assert tree["truncated"] is True
    assert tree["counts"]["generations"] == 1


def test_one_root_uses_a_synthetic_couple_and_still_traverses_parents(
    ancestor_family_db: Path,
) -> None:
    tree = get_ancestor_family_tree(ancestor_family_db, 1, 7, max_depth=1)

    assert tree is not None
    assert [root["person_id"] for root in tree["roots"]] == [7]
    assert [couple["marriage_id"] for couple in tree["couples"]] == ["root:7", 22]
    synthetic = tree["couples"][0]
    assert synthetic["root_couple"] is True
    assert synthetic["partner_person_ids"] == [7]
    assert synthetic["child_ids"] == []
    assert {
        (item["marriage_id"], item["spouse_person_id"]) for item in synthetic["alternative_spouses"]
    } == {
        (20, 8),
        (26, 17),
    }
    assert tree["links"] == [{"child_person_id": 7, "parent_couple_id": 22, "depth": 1}]
    assert tree["has_parents"] == [7, 11]
    assert tree["truncated"] is True


def test_missing_root_no_shared_couple_and_cycles_are_handled(
    ancestor_family_db: Path,
) -> None:
    assert get_ancestor_family_tree(ancestor_family_db, 1, 1, 9999) is None

    no_couple = get_ancestor_family_tree(ancestor_family_db, 1, 1, 4)
    assert no_couple is not None
    assert no_couple["status"] == "no_shared_couple"
    assert "recorded marriage" in no_couple["message"]
    assert no_couple["couples"] == []
    assert no_couple["links"] == []
    assert no_couple["has_parents"] == [1]
    assert no_couple["truncated"] is True
    assert no_couple["counts"]["people"] == 2

    tree = get_ancestor_family_tree(ancestor_family_db, 1, 1, 2, max_depth=6)
    assert tree is not None
    assert [couple["marriage_id"] for couple in tree["couples"]].count(10) == 1
    assert not any(link["parent_couple_id"] == 10 for link in tree["links"])


def test_full_tree_api_validation_optional_second_head_auth_and_status_mapping(
    ancestor_family_db: Path,
) -> None:
    with TestClient(create_app(ancestor_family_db)) as client:
        response = client.get(
            "/api/full-tree",
            params={"dataset": 1, "first": 1, "second": 2, "generations": 1},
        )
        assert response.status_code == 200
        assert response.json()["max_depth"] == 1

        one_root = client.get("/api/full-tree", params={"dataset": 1, "first": 7, "generations": 1})
        assert one_root.status_code == 200
        assert len(one_root.json()["roots"]) == 1

        capped = client.get(
            "/api/full-tree",
            params={"dataset": 1, "first": 1, "second": 2, "max_depth": 999},
        )
        assert capped.status_code == 200
        assert capped.json()["max_depth"] == 6

        head = client.head("/api/full-tree", params={"dataset": 1, "first": 1})
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
        missing = client.get("/api/full-tree", params={"dataset": 1, "first": 9999})
        assert missing.status_code == 404
        assert missing.json() == {"error": "One or both root people were not found"}
        no_couple = client.get("/api/full-tree", params={"dataset": 1, "first": 1, "second": 4})
        assert no_couple.status_code == 200
        assert no_couple.json()["status"] == "no_shared_couple"

    with TestClient(
        create_app(ancestor_family_db, password="family", session_secret="secret")
    ) as protected_client:
        assert (
            protected_client.get(
                "/api/full-tree", params={"dataset": 1, "first": 1, "second": 2}
            ).status_code
            == 401
        )


def test_ancestor_tree_uses_deterministic_targeted_indexable_queries(
    ancestor_family_db: Path,
) -> None:
    with sqlite3.connect(ancestor_family_db) as connection:
        connection.executemany(
            """INSERT INTO individuals
               (dataset_id, legacy_id, individual_id, given_name, surname, gender)
               VALUES (1, ?, ?, 'Unrelated', 'Bulk', 0)""",
            ((person_id, person_id) for person_id in range(20_000, 22_000)),
        )
        statements: list[str] = []
        connection.set_trace_callback(statements.append)
        tree = get_ancestor_family_tree(connection, 1, 1, 2, max_depth=2)

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
    assert all(" IN (" in statement.upper() for statement in marriage_selects)
    assert all(" IN (" in statement.upper() for statement in child_selects)
