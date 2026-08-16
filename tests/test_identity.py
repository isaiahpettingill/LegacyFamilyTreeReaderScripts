from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import PersonRow

from legacy_family_tree_reader.identity import (
    IdentityError,
    link_people,
    list_identity_groups,
    suggest_links,
)
from legacy_family_tree_reader.importer import import_database


def _person(person_id: int, birth_sort: int, *, surname: str = "Example") -> PersonRow:
    return (
        person_id,
        person_id,
        "Rene",
        surname,
        0,
        "000505198000000000",
        birth_sort,
        "",
        0,
        0,
        0,
        "",
        "",
        "",
        "",
    )


def test_identity_suggestions_are_conservative_and_do_not_mutate_groups(
    tmp_path: Path, raw_factory: Callable[..., Path]
) -> None:
    database = tmp_path / "identity.sqlite"
    import_database(raw_factory(marker="a", people=(_person(1, 19800505),)), database)
    import_database(raw_factory(marker="b", people=(_person(2, 19800505),)), database)
    import_database(raw_factory(marker="conflict", people=(_person(3, 19810505),)), database)
    import_database(
        raw_factory(marker="name", people=(_person(4, 19800505, surname="Different"),)),
        database,
    )

    suggestions = suggest_links(database)
    assert len(suggestions) == 1
    assert suggestions[0]["matched_on"] == ["normalized_name", "birth"]
    assert suggestions[0]["person_a"]["dataset_id"] == 1
    assert suggestions[0]["person_b"]["dataset_id"] == 2
    assert list_identity_groups(database) == []


def test_linking_extends_and_atomically_merges_identity_groups(
    tmp_path: Path, raw_factory: Callable[..., Path]
) -> None:
    database = tmp_path / "groups.sqlite"
    for dataset in range(1, 5):
        import_database(
            raw_factory(marker=str(dataset), people=(_person(dataset, 19800505),)),
            database,
        )

    first = link_people(database, 1, 1, 2, 2)
    second = link_people(database, 3, 3, 4, 4)
    assert first["group_id"] != second["group_id"]

    merged = link_people(database, 2, 2, 3, 3)
    assert merged["group_id"] == min(first["group_id"], second["group_id"])
    assert {(member["dataset_id"], member["person_id"]) for member in merged["members"]} == {
        (1, 1),
        (2, 2),
        (3, 3),
        (4, 4),
    }
    assert len(list_identity_groups(database)) == 1
    assert suggest_links(database) == []

    with pytest.raises(IdentityError, match="different datasets"):
        link_people(database, 1, 1, 1, 1)
    with pytest.raises(IdentityError, match="was not found"):
        link_people(database, 1, 999, 2, 2)
