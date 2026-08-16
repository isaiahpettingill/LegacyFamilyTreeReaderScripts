from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from legacy_family_tree_reader.importer import import_database

PersonRow = tuple[
    int,
    int,
    str,
    str,
    int,
    str,
    int,
    str,
    int,
    int,
    int,
    str,
    str,
    str,
    str,
]


FICTIONAL_PEOPLE: tuple[PersonRow, ...] = (
    (100, 1, "Alden", "North", 0, "001503195000000000", 19500315, "", 0, 0, 0, "", "", "", ""),
    (200, 2, "Bryn", "West", 1, "002006195200000000", 19520620, "", 0, 0, 0, "", "", "", ""),
    (
        300,
        3,
        "Casey Rowan",
        "Branch",
        0,
        "000407197500000000",
        19750704,
        "",
        0,
        0,
        0,
        "Synthetic general note",
        "Synthetic research note",
        "None",
        "",
    ),
    (400, 4, "Dana", "Reed", 1, "000102197600000000", 19760201, "", 0, 0, 0, "", "", "", ""),
    (500, 5, "Eli", "Twig", 0, "000303200000000000", 20000303, "", 0, 0, 0, "", "", "", ""),
    (600, 6, "Sage", "Branch", 1, "000808197800000000", 19780808, "", 0, 1, 1, "", "", "", ""),
)


def _create_raw_database(
    path: Path,
    *,
    marker: str,
    people: Sequence[PersonRow] = FICTIONAL_PEOPLE,
    rich: bool = False,
) -> Path:
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE tblHR (Item TEXT, Setting TEXT)")
        connection.executemany(
            "INSERT INTO tblHR VALUES (?, ?)",
            (("LegacyVer", "9.0"), ("SyntheticMarker", marker)),
        )
        connection.execute(
            """CREATE TABLE tblIR (
                ID INTEGER, IDIR INTEGER, GivenName TEXT, Surname TEXT, Gender INTEGER,
                BirthD TEXT, BirthSD INTEGER, DeathD TEXT, DeathSD INTEGER,
                Living INTEGER, Private INTEGER, Notes TEXT, [References] TEXT,
                Medical TEXT, DeathCause TEXT
            )"""
        )
        connection.executemany(
            "INSERT INTO tblIR VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            people,
        )
        if not rich:
            connection.commit()
            return path

        connection.execute(
            """CREATE TABLE tblNX (
                IDNX INTEGER, IDIR INTEGER, GivenName TEXT, Surname TEXT, PreferredAKA INTEGER
            )"""
        )
        connection.executemany(
            "INSERT INTO tblNX VALUES (?, ?, ?, ?, ?)",
            ((100, 3, "Morgan Casey", "Harbor", 1), (101, 4, "Dee", "Reed", 0)),
        )
        connection.execute(
            """CREATE TABLE tblMR (
                IDMR INTEGER, IDIRHusb INTEGER, IDIRWife INTEGER, MarD TEXT, Private INTEGER
            )"""
        )
        connection.executemany(
            "INSERT INTO tblMR VALUES (?, ?, ?, ?, ?)",
            (
                (10, 1, 2, "001001197000000000", 0),
                (11, 3, 4, "001201199800000000", 0),
            ),
        )
        connection.execute(
            "CREATE TABLE tblCR (IDCR INTEGER, IDMR INTEGER, IDIR INTEGER, [Order] INTEGER)"
        )
        connection.executemany(
            "INSERT INTO tblCR VALUES (?, ?, ?, ?)",
            ((102, 10, 3, 1), (103, 10, 6, 2), (104, 11, 5, 1)),
        )
        connection.execute(
            """CREATE TABLE tblLR (
                IDLR INTEGER, Location TEXT, SortedLocation TEXT, ShortName TEXT,
                Latitude REAL, Longitude REAL, Verified INTEGER
            )"""
        )
        connection.execute(
            "INSERT INTO tblLR VALUES (?, ?, ?, ?, ?, ?, ?)",
            (20, "Example Township", "Township, Example", "Example", 40.0, -75.0, 1),
        )
        connection.execute("CREATE TABLE tblET (IDET INTEGER, EventType TEXT)")
        connection.execute("INSERT INTO tblET VALUES (7, 'Residence')")
        connection.execute(
            """CREATE TABLE tblER (
                IDER INTEGER, IDET INTEGER, IDType INTEGER, IDIDOwner INTEGER,
                EventD TEXT, IDLREvent INTEGER, Description TEXT, [Desc] TEXT, GEDTag TEXT
            )"""
        )
        connection.execute(
            "INSERT INTO tblER VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (104, 7, 0, 300, "000000201000000000", 20, "Fictional residence", "", "RESI"),
        )
        connection.execute(
            "CREATE TABLE tblEX (IDEX INTEGER, IDIR INTEGER, IDER INTEGER, Given TEXT, Surname TEXT)"
        )
        connection.execute("INSERT INTO tblEX VALUES (105, 3, 104, 'Casey Rowan', 'Branch')")
        connection.execute("CREATE TABLE tblWS (IDWS INTEGER, StoryTitle TEXT, Story TEXT)")
        connection.execute(
            "INSERT INTO tblWS VALUES (107, 'A fictional story', 'No real family information.')"
        )
        connection.execute(
            "CREATE TABLE tblWX (IDWX INTEGER, IDWS INTEGER, IndiID INTEGER, [Order] INTEGER)"
        )
        connection.execute("INSERT INTO tblWX VALUES (108, 107, 3, 1)")
        connection.execute("CREATE TABLE tblTD (IDTD INTEGER, IDIR INTEGER, ToDoName TEXT)")
        connection.execute("INSERT INTO tblTD VALUES (106, 3, 'Check fictional record')")
        connection.execute("CREATE TABLE tblSR (IDSR INTEGER, SrcName TEXT, SrcTitle TEXT)")
        connection.execute("INSERT INTO tblSR VALUES (50, 'Synthetic source', 'Example register')")
        connection.execute(
            """CREATE TABLE tblSX (
                IDSX INTEGER, IDSR INTEGER, IDIME INTEGER, Type INTEGER,
                SrcDetail TEXT, FullCitation TEXT
            )"""
        )
        person_types = (0, 1, 2, 3, 4, 5, 15, 16, 26, 27)
        grouped_targets = (
            *((type_code, 3) for type_code in person_types),
            (10, 100),
            (12, 106),
            (13, 106),
            (17, 102),
            (18, 11),
            (20, 11),
            (28, 107),
            (30, 104),
            (31, 105),
        )
        connection.executemany(
            "INSERT INTO tblSX VALUES (?, 50, ?, ?, ?, ?)",
            (
                (index, target, type_code, f"Page {index}", f"Synthetic citation {index}")
                for index, (type_code, target) in enumerate(grouped_targets, start=1)
            ),
        )
        connection.execute(
            "INSERT INTO tblSX VALUES (999, 50, 9999, 30, 'Unrelated', 'Must not resolve')"
        )
        connection.execute("CREATE TABLE tblBP (IDBP INTEGER, PicPath TEXT)")
        connection.execute("INSERT INTO tblBP VALUES (1, 'synthetic-media')")
        connection.execute(
            """CREATE TABLE tblBR (
                IDBR INTEGER, IDIR INTEGER, IDType INTEGER, PicName TEXT,
                PicCaption TEXT, IDBPPic INTEGER
            )"""
        )
        connection.execute(
            "INSERT INTO tblBR VALUES (70, 3, 0, 'portrait.txt', 'Synthetic portrait', 1)"
        )
        connection.commit()
        return path
    finally:
        connection.close()


@pytest.fixture
def raw_factory(tmp_path: Path) -> Callable[..., Path]:
    counter = 0

    def make_raw(
        *,
        marker: str | None = None,
        people: Sequence[PersonRow] = FICTIONAL_PEOPLE,
        rich: bool = False,
    ) -> Path:
        nonlocal counter
        counter += 1
        effective_marker = marker or f"fixture-{counter}"
        return _create_raw_database(
            tmp_path / f"raw-{counter}.sqlite",
            marker=effective_marker,
            people=people,
            rich=rich,
        )

    return make_raw


@pytest.fixture
def merged_db(tmp_path: Path, raw_factory: Callable[..., Path]) -> Path:
    database = tmp_path / "merged.sqlite"
    import_database(raw_factory(marker="rich", rich=True), database, "Fictional family")
    other_person: PersonRow = (
        100,
        1,
        "Other",
        "Dataset",
        0,
        "000101198000000000",
        19800101,
        "",
        0,
        0,
        0,
        "",
        "",
        "",
        "",
    )
    import_database(
        raw_factory(marker="other", people=(other_person,)),
        database,
        "Separate dataset",
    )
    return database
