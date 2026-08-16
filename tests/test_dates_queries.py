from __future__ import annotations

from pathlib import Path

import pytest

from legacy_family_tree_reader.dates import decode_legacy_date
from legacy_family_tree_reader.queries import (
    get_ancestors,
    get_descendants,
    get_family,
    get_person_facts,
    list_people,
    search_people,
    shortest_relationship_path,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        (None, None),
        ("", None),
        (0, None),
        (-99999999, None),
        ("000407197500000000", "1975-07-04"),
        ("000007197500000000", "1975-07"),
        ("000000197500000000", "1975"),
        (19750704, "1975-07-04"),
        ("011503195000000000", "011503195000000000"),
        ("003202197500000000", "003202197500000000"),
        ("about 1975", "about 1975"),
    ),
)
def test_conservative_legacy_date_decoding(value: object, expected: str | None) -> None:
    assert decode_legacy_date(value) == expected


def test_tokenized_primary_and_alternate_name_search_is_dataset_scoped(merged_db: Path) -> None:
    primary = search_people(merged_db, 1, "branch casey")
    alternate = search_people(merged_db, 1, "harbor morgan")
    mixed = search_people(merged_db, 1, "Branch Morgan")

    assert [row["person_id"] for row in primary] == [3]
    assert [row["person_id"] for row in alternate] == [3]
    assert [row["person_id"] for row in mixed] == [3]
    assert search_people(merged_db, 2, "Casey") == []
    assert search_people(merged_db, 1, "%") == []
    assert search_people(merged_db, 1, "   ") == []


def test_people_list_is_alphabetical_and_paginated(merged_db: Path) -> None:
    first = list_people(merged_db, 1, limit=2)
    second = list_people(merged_db, 1, limit=2, offset=2)

    assert first["total"] == 6
    assert first["has_more"] is True
    assert len(first["people"]) == 2
    assert second["offset"] == 2
    assert {row["person_id"] for row in first["people"]}.isdisjoint(
        row["person_id"] for row in second["people"]
    )


def test_family_trees_and_shortest_paths_use_legacy_gender_zero_one(merged_db: Path) -> None:
    family = get_family(merged_db, 1, 3)
    assert family is not None
    assert {row["person_id"] for row in family["parents"]} == {1, 2}
    assert [row["person_id"] for row in family["spouses"]] == [4]
    assert [row["person_id"] for row in family["children"]] == [5]
    assert [row["person_id"] for row in family["siblings"]] == [6]

    ancestors = get_ancestors(merged_db, 1, 3, max_depth=2)
    assert ancestors is not None
    assert {(row["person_id"], row["relationship"]) for row in ancestors["people"]} == {
        (1, "father"),
        (2, "mother"),
    }
    descendants = get_descendants(merged_db, 1, 1, max_depth=2)
    assert descendants is not None
    assert {(row["person_id"], row["relationship"]) for row in descendants["people"]} == {
        (3, "son"),
        (5, "son"),
        (6, "daughter"),
    }

    spouse_path = shortest_relationship_path(merged_db, 1, 1, 2)
    assert spouse_path["found"] is True
    assert spouse_path["steps"][0]["relationship"] == "wife"
    grandchild_path = shortest_relationship_path(merged_db, 1, 2, 5)
    assert grandchild_path["length"] == 2
    assert [step["relationship"] for step in grandchild_path["steps"]] == ["son", "son"]
    assert shortest_relationship_path(merged_db, 1, 1, 999)["found"] is False


def test_person_citations_resolve_every_supported_polymorphic_target_family(
    merged_db: Path,
) -> None:
    facts = get_person_facts(merged_db, 1, 3)
    assert facts is not None
    expected_types = {0, 1, 2, 3, 4, 5, 10, 12, 13, 15, 16, 17, 18, 20, 26, 27, 28, 30, 31}
    assert {row["type"] for row in facts["citations"]} == expected_types
    assert 999 not in {row["citation_id"] for row in facts["citations"]}
    assert {row["source_id"] for row in facts["sources"]} == {50}
    assert [row["alternate_name_id"] for row in facts["alternate_names"]] == [100]
    assert [row["event_id"] for row in facts["events"]] == [104]
