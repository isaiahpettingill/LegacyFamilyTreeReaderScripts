"""Canonical, descriptive schema for Legacy Family Tree 9 databases.

Legacy uses terse Access names.  This module is the single source of truth for
the 38 tables and 522 columns present in a Legacy 9 family file.  Source names
are retained in the metadata tables while application tables use stable,
descriptive snake-case names.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

SCHEMA_VERSION = 1
LEGACY_SCHEMA_VERSION = "9"


@dataclass(frozen=True, slots=True)
class Column:
    source_name: str
    name: str
    storage_type: str
    description: str


@dataclass(frozen=True, slots=True)
class Table:
    source_name: str
    name: str
    description: str
    columns: tuple[Column, ...]


# A name followed by ``~`` is text and one followed by ``#`` is real.  All
# other Legacy fields are integers.  Keeping this compact makes the complete
# vendor schema auditable without hiding any columns in external resources.
_DEFINITIONS: tuple[tuple[str, str, str, str], ...] = (
    (
        "tblAR",
        "addresses",
        "Addresses, repositories, and contact details",
        """
        IDAR Kind Style AddrName~ AddrSort~ Address1~ Address2~ City~ State~ ZipCode~
        Country~ Latitude# Longitude# Phone1~ Phone2~ Email~ HomePage~ AddrNotes~
        List1 List2 List3 List4 List5 List6 Private Tag1 Used Verified FSResolved VEResolved
    """,
    ),
    ("tblBP", "media_paths", "Media base paths", "IDBP PicPath~ Used Tag1"),
    (
        "tblBR",
        "media",
        "Pictures, documents, sounds, and other media",
        """
        IDBR IDIR IDType PicType PicOrder PicName~ PicNameURL~ IDBPPic PicCaption~
        PicDate~ PicDesc~ PicPrint PicSoundName~ PicSoundNameURL~ IDBPSound Used PicPref
        FilingRef~
    """,
    ),
    (
        "tblCP",
        "child_relationship_types",
        "Child-to-parent relationship types",
        "IDCP CPRelation~ Tag1 Used",
    ),
    (
        "tblCR",
        "children",
        "Children linked to marriages and parents",
        """
        IDCR IDMR IDIR Order PrefChild IDCS IDCPDad IDCPMom CPDadPrivate CPMomPrivate
        ParSealD~ ParSealSD IDTRParSeal ParSealNote~ LDSP TempleTag
    """,
    ),
    ("tblCS", "child_statuses", "Child status values", "IDCS ChildStatus~ Used Tag1"),
    (
        "tblDM",
        "duplicate_individuals",
        "Potential duplicate individual pairs",
        "IDIRLeft IDIRRight",
    ),
    (
        "tblER",
        "events",
        "Individual and marriage events",
        """
        IDER IDET IDType IDIDOwner EventD~ EventSD IDLREvent Desc~ AddNotes GEDTag~ IDAR
        Description~ SentenceOverride~
    """,
    ),
    (
        "tblET",
        "event_types",
        "Event type definitions and narrative sentences",
        """
        IDET EventType~ ShowDate ShowPlace ShowDescription Sentence~ Sentence2~ Sentence3~
        Sentence4~ Sentence5~ Sentence6~ Sentence7~ Sentence8~ AddNotes Private PPExclude
        Used Tag1
    """,
    ),
    (
        "tblEX",
        "event_participants",
        "People sharing or participating in events",
        """
        IDEX IDType IDIR Order IDERType IDER IDRO Given~ Surname~ Notes~ SentenceOverride~
        AddSharedNotes Private PPExclude RGExclude
    """,
    ),
    (
        "tblFP",
        "focus_projects",
        "Focus-group and research project definitions",
        """
        IDFP ProjName~ ProjType AGens DGens TagValue IncSPKids BaseRef~ Complete LastUpdate~
        Created~ IncList~ ExcList~
    """,
    ),
    (
        "tblFS",
        "familysearch_data",
        "FamilySearch synchronization state",
        """
        IDIR FSID~ FSSync FSOrdinance FSVersion~ HasDups TempleCount TempleDone TaskMatch
        TaskSearch TaskDups TaskSync TaskStand TaskTemple LastUpdate~ UpdateTaskVersion~
        MatchExclude~ MatchNever~ MatchSkip~
    """,
    ),
    (
        "tblFX",
        "database_settings",
        "Database settings and structured configuration",
        "Item~ Setting~",
    ),
    ("tblGP", "groups", "Named individual groups", "IDGP GroupName~ GroupDesc~ Used Tag1"),
    ("tblGX", "group_memberships", "Individuals assigned to groups", "IDGX IDGP IndiID"),
    ("tblHB", "history_bookmarks", "Legacy history bookmark records", "IDHB IDIR IDMR"),
    ("tblHL", "history_links", "Legacy individual and marriage history links", "IDHL IDIR IDMR"),
    ("tblHR", "legacy_settings", "Legacy file settings and version information", "Item~ Setting~"),
    (
        "tblIR",
        "individuals",
        "Individual people",
        """
        ID IDIR Surname~ SoundsLike~ GivenName~ Prefix~ Title~ NameNote~ Gender BirthD~
        BirthSD IDLRBirth ChrisD~ ChrisSD IDLRChris ChrTerm~ DeathD~ DeathSD IDLRDeath
        BuriedD~ BuriedSD IDLRBuried Cremated IDARBirth IDARChris IDARDeath IDARBuried
        BirthNote~ ChrisNote~ DeathNote~ BuriedNote~ Living BaptismD~ BaptismSD BaptismKind
        IDTRBaptism BaptismNote~ LDSB ConfirmationD~ ConfirmationSD ConfirmationKind
        IDTRConfirmation ConfirmationNote~ LDSC InitiatoryD~ InitiatorySD IDTRInitiatory
        InitiatoryNote~ LDSI EndowD~ EndowSD IDTREndow EndowNote~ LDSE TempleTag IDMRPref
        IDMRParents IDAR AncInterest DecInterest Tag1 Tag2 Tag3 Tag4 Tag5 Tag6 Tag7 Tag8 Tag9
        TagGroup TagAnc TagDec SaveTag SrchTag SrchTagRG qsTag ReminderTag ReminderTagDeath
        TreeNum LTMP1 LTMP2 AlreadyUsed UserRef~ AncestralRef~ Notes~ References~ Medical~
        DeathCause~ PPCheck Imported Added AddedTime~ Updated UpdatedTime~ Relations~
        NeverMarried DirectLine STMP1~ ColorTag1 ColorTag2 IntelliShare~ Private PPExclude~
        RGExclude DNA~ FSActive Hints
    """,
    ),
    ("tblIV", "indexed_values", "Internal indexed values", "Kind ID Value~"),
    (
        "tblLR",
        "locations",
        "Place and location records",
        """
        IDLR FSPlaceID~ Preposition~ Location~ SortedLocation~ ShortName~ Tag1 Used Notes~
        Verified Latitude# Longitude# FSResolved VEResolved
    """,
    ),
    (
        "tblMR",
        "marriages",
        "Marriages and partnerships",
        """
        ID IDMR IDIRHusb HusbOrder HusbPrefMar HusbSurname~ HusbGivenName~ HusbMarrSurname~
        HusbBirthSD IDIRWife WifeOrder WifePrefMar WifeSurname~ WifeGivenName~
        WifeMarrSurname~ WifeBirthSD MarriedNameRule IDMS MarD~ MarSD MarEndD~ MarEndSD
        IDLRMar SealD~ SealSD IDTRSeal SealNote~ LDSS TempleTag Tag1 Tag2 Tag3 Tag4 Tag5
        Tag6 Tag7 Tag8 Tag9 TagGroup SrchTag ReminderTag NotMarried NoChildren AlreadyUsed
        LTMP1 LTMP2 Notes~ PPCheck Added AddedTime~ Updated UpdatedTime~ IDAR HPhrase~ WPhrase~
        RPhrase~ RPhrase2~ UserRef~ MPhrase~ SPhrase~ HusbWifeOver1~ HusbWifeOver2~
        WifeHusbOver1~ WifeHusbOver2~ Private
    """,
    ),
    ("tblMS", "marriage_statuses", "Marriage status values", "IDMS MarStatus~ Used Tag1"),
    ("tblNR", "surnames", "Surname index", "IDNR Surname~ Used Tag1"),
    (
        "tblNX",
        "alternate_names",
        "Alternate and married names",
        """
        IDNX IDNR IDIR Order MarriedNameCreatedBy MarriedNameMarIDID Prefix~ Title~ Surname~
        GivenName~ SoundsLike~ UserRef~ AKANote~ PreferredAKA BirthSD SrchTag qsTag
    """,
    ),
    (
        "tblRM",
        "reminders",
        "Research reminders",
        """
        IDRM ReminderTitle~ ReminderD~ ReminderSD ReminderNote~
    """,
    ),
    (
        "tblRO",
        "event_roles",
        "Event participant role definitions",
        """
        IDRO EventName~ Role~ DefaultRole Sentence~ Sentence2~ Sentence3~ Sentence4~
        Sentence5~ Sentence6~ Sentence7~ Sentence8~ Tag1 Used
    """,
    ),
    (
        "tblSR",
        "sources",
        "Master source records",
        """
        IDSR SrcName~ SrcTitle~ SrcAuthor~ SrcPubl~ SrcText~ SrcNote~ SrcTag SrcExclude IDST Used
        pSrcNote fSrcNote tSrcNote pSrcText fSrcText tSrcText IDAR EnteredSD FilingRef~
        SrcCallNum~ Verified Published EnteredD~ SrcMPub~ SrcRollNum~ TemplateID Contents~
        UseStandard IDAR2 Bibliography Override~ OverrideFootnote OverrideSubsequent
        OverrideBibliography URL~
    """,
    ),
    ("tblST", "source_types", "Source type values", "IDST SrcType~ Used Tag1"),
    (
        "tblSX",
        "citations",
        "Source citations attached to records",
        """
        IDSX IDSR IDIME Type SrcDetail~ SrcSurety SrcPrint SrcPrintDetail SrcPrintText
        SrcDetText~ SrcDetNote~ SrcPrintNote SrcSource SrcInfo SrcEvidence EnteredD~ EnteredSD
        FilingRef~ Order Used Verified Content~ Override~ OverrideFootnote OverrideSubsequent
        OverrideBibliography FullCitation~
    """,
    ),
    ("tblTC", "todo_categories", "To-do categories", "IDTC Category~ Tag1 Used"),
    (
        "tblTD",
        "todos",
        "Research to-do items",
        """
        IDTD ToDoType IDIR IDTC IDTL ToDoName~ OpenedD~ OpenedSD ReminderD~ ReminderSD
        ClosedD~ IDAR Status Priority Desc~ Results~ FilingRef~ Tag1 Used
    """,
    ),
    ("tblTL", "todo_localities", "To-do locality values", "IDTL Locality~ Tag1 Used"),
    (
        "tblTR",
        "temples",
        "LDS temple definitions",
        """
        IDTR Temple~ TempleStart TempleEnd Used Tag1
    """,
    ),
    (
        "tblWS",
        "stories",
        "Legacy stories",
        """
        IDWS StoryTitle~ StoryD~ StorySD IDLRStory Story~ Used Tag1
    """,
    ),
    (
        "tblWX",
        "story_individuals",
        "Individuals linked to stories",
        "IDWX IDWS IndiID Order Private",
    ),
    ("tblXI", "deleted_individuals", "Deleted individual identifiers", "DeletedID"),
    ("tblXM", "deleted_marriages", "Deleted marriage identifiers", "DeletedID"),
)

_ID_ENTITIES = {
    "AR": "address",
    "BP": "media_path",
    "BR": "media",
    "CP": "child_relationship_type",
    "CR": "child",
    "CS": "child_status",
    "ER": "event",
    "ET": "event_type",
    "EX": "event_participant",
    "FP": "focus_project",
    "GP": "group",
    "GX": "group_membership",
    "HB": "history_bookmark",
    "HL": "history_link",
    "IR": "individual",
    "LR": "location",
    "MR": "marriage",
    "MS": "marriage_status",
    "NR": "surname",
    "NX": "alternate_name",
    "RM": "reminder",
    "RO": "event_role",
    "SR": "source",
    "ST": "source_type",
    "SX": "citation",
    "TC": "todo_category",
    "TD": "todo",
    "TL": "todo_locality",
    "TR": "temple",
    "WS": "story",
    "WX": "story_individual",
}

_COLUMN_OVERRIDES = {
    "ID": "legacy_id",
    "IndiID": "individual_id",
    "DeletedID": "deleted_id",
    "IDIDOwner": "owner_record_id",
    "IDIME": "cited_record_id",
    "IDType": "record_type",
    "IDERType": "event_record_type",
    "IDIRHusb": "husband_individual_id",
    "IDIRWife": "wife_individual_id",
    "IDIRLeft": "left_individual_id",
    "IDIRRight": "right_individual_id",
    "IDMRPref": "preferred_marriage_id",
    "IDMRParents": "parents_marriage_id",
    "IDCPDad": "father_relationship_type_id",
    "IDCPMom": "mother_relationship_type_id",
    "IDTRParSeal": "parent_sealing_temple_id",
    "IDLRBirth": "birth_location_id",
    "IDLRChris": "christening_location_id",
    "IDLRDeath": "death_location_id",
    "IDLRBuried": "burial_location_id",
    "IDARBirth": "birth_address_id",
    "IDARChris": "christening_address_id",
    "IDARDeath": "death_address_id",
    "IDARBuried": "burial_address_id",
    "IDTRBaptism": "baptism_temple_id",
    "IDTRConfirmation": "confirmation_temple_id",
    "IDTRInitiatory": "initiatory_temple_id",
    "IDTREndow": "endowment_temple_id",
    "IDLREvent": "event_location_id",
    "IDLRMar": "marriage_location_id",
    "IDTRSeal": "sealing_temple_id",
    "IDLRStory": "story_location_id",
    "IDBPPic": "picture_media_path_id",
    "IDBPSound": "sound_media_path_id",
    "IDAR2": "secondary_address_id",
    "MarriedNameMarIDID": "married_name_marriage_record_id",
    "AGens": "ancestor_generations",
    "DGens": "descendant_generations",
    "IncSPKids": "include_spouse_children",
    "ChrTerm": "christening_term",
    "EndowD": "endowment_date",
    "EndowSD": "endowment_sort_date",
    "EndowNote": "endowment_note",
    "LDSB": "lds_baptism_status",
    "LDSC": "lds_confirmation_status",
    "LDSI": "lds_initiatory_status",
    "LDSE": "lds_endowment_status",
    "LDSP": "lds_parent_sealing_status",
    "LDSS": "lds_spouse_sealing_status",
    "LTMP1": "legacy_temporary_integer_1",
    "LTMP2": "legacy_temporary_integer_2",
    "STMP1": "legacy_temporary_text_1",
    "PPCheck": "potential_problems_checked",
    "PPExclude": "potential_problems_excluded",
    "VEResolved": "virtual_earth_resolved",
    "Order": "display_order",
    "Desc": "description",
    "Given": "given_name",
    "FSID": "familysearch_id",
    "FSPlaceID": "familysearch_place_id",
    "qsTag": "quick_search_tag",
}

_WORD_REPLACEMENTS = {
    "addr": "address",
    "anc": "ancestor",
    "aka": "alternate_name",
    "buried": "burial",
    "chris": "christening",
    "cp": "child_parent",
    "dec": "descendant",
    "det": "detail",
    "dups": "duplicates",
    "exc": "excluded",
    "fs": "familysearch",
    "ged": "gedcom",
    "gens": "generations",
    "husb": "husband",
    "inc": "included",
    "indi": "individual",
    "lds": "lds",
    "lr": "location",
    "mar": "marriage",
    "marr": "married",
    "mpub": "master_publication",
    "par": "parent",
    "pic": "media",
    "pref": "preferred",
    "proj": "project",
    "publ": "publication",
    "rg": "report",
    "src": "source",
    "srch": "search",
    "stand": "standards",
    "todo": "todo",
    "tr": "temple",
    "wife": "wife",
}


def _snake(name: str) -> str:
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    return name.lower()


def _column_name(source_name: str) -> str:
    if source_name in _COLUMN_OVERRIDES:
        return _COLUMN_OVERRIDES[source_name]
    for code in sorted(_ID_ENTITIES, key=len, reverse=True):
        prefix = f"ID{code}"
        if source_name == prefix:
            return f"{_ID_ENTITIES[code]}_id"
    if source_name.endswith("SD") and not source_name.startswith("ID"):
        return f"{_column_name(source_name[:-2])}_sort_date"
    if source_name.endswith("D") and not source_name.startswith("ID"):
        return f"{_column_name(source_name[:-1])}_date"
    words = _snake(source_name).split("_")
    return "_".join(_WORD_REPLACEMENTS.get(word, word) for word in words)


def _description(name: str) -> str:
    return name.replace("_", " ").capitalize()


def _build_tables() -> tuple[Table, ...]:
    tables: list[Table] = []
    for source_name, name, description, declaration in _DEFINITIONS:
        columns: list[Column] = []
        for token in declaration.split():
            marker = token[-1] if token[-1] in "~#" else ""
            raw_name = token[:-1] if marker else token
            storage_type = {"~": "TEXT", "#": "REAL"}.get(marker, "INTEGER")
            target_name = _column_name(raw_name)
            if source_name == "tblER" and raw_name == "Desc":
                target_name = "notes"
            elif source_name == "tblBR" and raw_name == "IDIR":
                target_name = "owner_record_id"
            columns.append(Column(raw_name, target_name, storage_type, _description(target_name)))
        tables.append(Table(source_name, name, description, tuple(columns)))
    return tuple(tables)


TABLES = _build_tables()
TABLE_BY_SOURCE = {table.source_name.casefold(): table for table in TABLES}
TABLE_BY_NAME = {table.name: table for table in TABLES}

if len(TABLES) != 38 or sum(len(table.columns) for table in TABLES) != 522:
    raise RuntimeError("Legacy 9 schema catalog must contain exactly 38 tables and 522 columns")
for _table in TABLES:
    _names = [column.name for column in _table.columns]
    if len(_names) != len(set(_names)):
        raise RuntimeError(f"duplicate descriptive column in {_table.source_name}")


def quote_identifier(name: str) -> str:
    """Quote a trusted or externally supplied SQLite identifier."""

    return '"' + name.replace('"', '""') + '"'


def create_schema(connection: sqlite3.Connection) -> None:
    """Create or verify the merged descriptive database schema."""

    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("""
        CREATE TABLE IF NOT EXISTS datasets (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            source_path TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            source_format TEXT NOT NULL,
            legacy_version TEXT
        )
    """)
    connection.execute("CREATE INDEX IF NOT EXISTS datasets_sha256_idx ON datasets(sha256)")
    connection.execute("""
        CREATE TABLE IF NOT EXISTS schema_metadata (
            source_table TEXT PRIMARY KEY,
            table_name TEXT NOT NULL UNIQUE,
            description TEXT NOT NULL,
            legacy_version TEXT NOT NULL,
            schema_version INTEGER NOT NULL
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS schema_columns (
            source_table TEXT NOT NULL,
            source_column TEXT NOT NULL,
            table_name TEXT NOT NULL,
            column_name TEXT NOT NULL,
            ordinal INTEGER NOT NULL,
            storage_type TEXT NOT NULL,
            description TEXT NOT NULL,
            PRIMARY KEY (source_table, source_column)
        )
    """)

    for table in TABLES:
        definitions = [
            "dataset_id INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE",
            *(f"{quote_identifier(c.name)} {c.storage_type}" for c in table.columns),
        ]
        connection.execute(
            f"CREATE TABLE IF NOT EXISTS {quote_identifier(table.name)} ({', '.join(definitions)})"
        )
        connection.execute(
            f"CREATE INDEX IF NOT EXISTS {quote_identifier(table.name + '_dataset_idx')} "
            f"ON {quote_identifier(table.name)}(dataset_id)"
        )
        connection.execute(
            "INSERT OR REPLACE INTO schema_metadata VALUES (?, ?, ?, ?, ?)",
            (
                table.source_name,
                table.name,
                table.description,
                LEGACY_SCHEMA_VERSION,
                SCHEMA_VERSION,
            ),
        )
        connection.executemany(
            "INSERT OR REPLACE INTO schema_columns VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                (
                    table.source_name,
                    column.source_name,
                    table.name,
                    column.name,
                    ordinal,
                    column.storage_type,
                    column.description,
                )
                for ordinal, column in enumerate(table.columns)
            ),
        )
    _create_indexes(connection)
    _create_views(connection)


def _create_indexes(connection: sqlite3.Connection) -> None:
    indexes = {
        "individuals": (("individual_id",), ("surname", "given_name"), ("parents_marriage_id",)),
        "marriages": (("marriage_id",), ("husband_individual_id",), ("wife_individual_id",)),
        "children": (("marriage_id", "display_order"), ("individual_id",)),
        "events": (("event_id",), ("owner_record_id", "record_type"), ("event_type_id",)),
        "event_participants": (("event_id",), ("individual_id",)),
        "locations": (("location_id",), ("sorted_location",)),
        "sources": (("source_id",), ("source_name",)),
        "citations": (("source_id",), ("cited_record_id", "type")),
        "media": (("media_id",), ("owner_record_id", "record_type")),
        "alternate_names": (("individual_id",), ("surname", "given_name")),
    }
    for table_name, groups in indexes.items():
        available = {column.name for column in TABLE_BY_NAME[table_name].columns}
        for columns in groups:
            if not set(columns) <= available:
                continue
            suffix = "_".join(columns)
            quoted = ", ".join(quote_identifier(column) for column in columns)
            connection.execute(
                f"CREATE INDEX IF NOT EXISTS {quote_identifier(table_name + '_' + suffix + '_idx')} "
                f"ON {quote_identifier(table_name)}(dataset_id, {quoted})"
            )


def _create_views(connection: sqlite3.Connection) -> None:
    statements = {
        "people": """
            SELECT i.dataset_id, i.individual_id, i.given_name, i.surname, i.prefix, i.title,
                   i.gender, i.birth_date, bl.location AS birth_place,
                   i.death_date, dl.location AS death_place, i.living, i.private
            FROM individuals AS i
            LEFT JOIN locations AS bl ON bl.dataset_id=i.dataset_id
                AND bl.location_id=i.birth_location_id
            LEFT JOIN locations AS dl ON dl.dataset_id=i.dataset_id
                AND dl.location_id=i.death_location_id
        """,
        "marriage_summary": """
            SELECT m.dataset_id, m.marriage_id, m.husband_individual_id,
                   trim(coalesce(h.given_name,'') || ' ' || coalesce(h.surname,'')) AS husband,
                   m.wife_individual_id,
                   trim(coalesce(w.given_name,'') || ' ' || coalesce(w.surname,'')) AS wife,
                   m.marriage_date, l.location AS marriage_place, ms.marriage_status
            FROM marriages AS m
            LEFT JOIN individuals AS h ON h.dataset_id=m.dataset_id
                AND h.individual_id=m.husband_individual_id
            LEFT JOIN individuals AS w ON w.dataset_id=m.dataset_id
                AND w.individual_id=m.wife_individual_id
            LEFT JOIN locations AS l ON l.dataset_id=m.dataset_id
                AND l.location_id=m.marriage_location_id
            LEFT JOIN marriage_statuses AS ms ON ms.dataset_id=m.dataset_id
                AND ms.marriage_status_id=m.marriage_status_id
        """,
        "families": """
            SELECT c.dataset_id, c.marriage_id, c.display_order AS child_order,
                   c.individual_id AS child_individual_id, p.given_name AS child_given_name,
                   p.surname AS child_surname, m.husband_individual_id, m.wife_individual_id
            FROM children AS c
            LEFT JOIN individuals AS p ON p.dataset_id=c.dataset_id
                AND p.individual_id=c.individual_id
            LEFT JOIN marriages AS m ON m.dataset_id=c.dataset_id
                AND m.marriage_id=c.marriage_id
        """,
        "event_summary": """
            SELECT e.dataset_id, e.event_id, e.owner_record_id, e.record_type,
                   et.event_type, e.event_date, l.location, e.description, e.gedcom_tag
            FROM events AS e
            LEFT JOIN event_types AS et ON et.dataset_id=e.dataset_id
                AND et.event_type_id=e.event_type_id
            LEFT JOIN locations AS l ON l.dataset_id=e.dataset_id
                AND l.location_id=e.event_location_id
        """,
        "citation_summary": """
            SELECT c.dataset_id, c.citation_id, c.cited_record_id, c.type AS cited_record_type,
                   c.source_id, s.source_name, s.source_title, c.source_detail,
                   c.full_citation
            FROM citations AS c
            LEFT JOIN sources AS s ON s.dataset_id=c.dataset_id AND s.source_id=c.source_id
        """,
        "media_summary": """
            SELECT m.dataset_id, m.media_id, m.owner_record_id,
                   m.record_type, m.media_name, m.media_caption, m.media_date,
                   p.media_path, m.filing_ref
            FROM media AS m
            LEFT JOIN media_paths AS p ON p.dataset_id=m.dataset_id
                AND p.media_path_id=m.picture_media_path_id
        """,
    }
    for name, select_sql in statements.items():
        connection.execute(f"CREATE VIEW IF NOT EXISTS {quote_identifier(name)} AS {select_sql}")


__all__ = [
    "LEGACY_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "TABLES",
    "TABLE_BY_NAME",
    "TABLE_BY_SOURCE",
    "Column",
    "Table",
    "create_schema",
    "quote_identifier",
]
