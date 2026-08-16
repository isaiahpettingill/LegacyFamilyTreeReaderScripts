# Legacy Family Tree Reader Scripts

Read Legacy Family Tree 9 databases without Legacy Family Tree or Microsoft
Access. The tools import FDB/MDB files into a descriptive SQLite schema, keep
multiple source datasets isolated, provide local browsing and JSON queries, and
export GEDCOM 5.5.1 or Excel workbooks.

The project is alpha software. Keep backups of every original database and
verify important results against the source application when possible.

## Requirements

- Python 3.11 or newer
- [uv](https://docs.astral.sh/uv/)
- `mdbtools`, specifically `mdb-tables` and `mdb-export`, when reading FDB/MDB
  files directly

Raw SQLite dumps can be imported without `mdbtools`.

Install the command-line tool directly from GitHub:

```console
uv tool install git+https://github.com/isaiahpettingill/LegacyFamilyTreeReaderScripts
legacy-family-tree --help
```

Install `mdbtools` with your operating system's package manager, or use the
provided Clang/LLVM builder after installing its native prerequisites: Git,
Clang, make, autoconf, automake, libtool, `pkg-config`, and GLib development
headers.

```console
legacy-family-tree build-mdbtools
```

The builder checks out the upstream `mdbtools` `dev` ref under
`~/.cache/legacy-family-tree-reader/mdbtools`, builds out of tree with
`CC=clang` and `CXX=clang++`, and installs under `~/.local` by default. Use
`legacy-family-tree build-mdbtools --help` for ref, directory, prefix, jobs, and
dry-run options. A repository checkout also provides the equivalent
`scripts/build-mdbtools-llvm.sh` helper. Ensure the selected prefix's `bin`
directory is on `PATH`.

## Import And Merge

Import an FDB directly into a new descriptive SQLite database:

```console
legacy-family-tree import example-family.fdb genealogy.sqlite --name "Primary research"
```

Import another source into the same database:

```console
legacy-family-tree import archive-dump.sqlite genealogy.sqlite --name "Archive copy"
```

Or merge several FDB/MDB files and raw SQLite dumps in one invocation:

```console
legacy-family-tree merge genealogy.sqlite example-family.fdb archive-dump.sqlite \
  --name "Primary research" --name "Archive copy"
```

Each source passed to `import` or `merge` becomes a new dataset. Every imported
row carries its generated `dataset_id`; Legacy record IDs remain source-local,
so matching numeric IDs from two files do not collide. Use one raw dump per
logical source if dataset isolation must be retained.

The importer calculates SHA-256 over each complete source file and rejects a
digest already present in the destination. `--allow-duplicate` overrides this
safety check; it does not reconcile or deduplicate people. Imports are
transactional per source. List dataset IDs and provenance with:

```console
legacy-family-tree datasets genealogy.sqlite
```

Do not merge a Legacy HDB file with an FDB as genealogy. An HDB is an auxiliary
Legacy history database, not another family dataset; appending its records to
FDB tables loses their meaning and can create misleading ID collisions. The
descriptive importer intentionally accepts family databases (`.fdb`, `.mdb`,
`.accdb`) and raw SQLite dumps, not `.hdb` files.

### Raw compatibility conversion

`mdb2sqlite` creates a compatibility database with the original `tbl*` table
and column names. **The output is always first**, followed by one or more
sources:

```console
mdb2sqlite raw.sqlite example-family.fdb
legacy-family-tree mdb2sqlite combined-raw.sqlite source-a.fdb source-b.fdb
```

This mode appends sources without `dataset_id` isolation, provenance rows, or
SHA duplicate checks. Prefer `legacy-family-tree import` or `merge` for normal
genealogy work. Never use the historical `FDB HDB OUTPUT` ordering: opening a
source path as SQLite output could damage it, and HDB data should not be
combined with family records.

## Query Data

Commands print JSON. Use the numeric dataset ID reported by `datasets`; person
IDs are the source dataset's Legacy individual IDs.

```console
# Name search, including alternate names
legacy-family-tree search genealogy.sqlite 1 "Alex Example" --limit 20

# Basic person record and all attached facts
legacy-family-tree person genealogy.sqlite 1 100
legacy-family-tree facts genealogy.sqlite 1 100

# Parents, spouses, children, siblings, and marriages
legacy-family-tree family genealogy.sqlite 1 100

# Ancestor and descendant trees
legacy-family-tree ancestors genealogy.sqlite 1 100 --depth 6
legacy-family-tree descendants genealogy.sqlite 1 100 --depth 4

# Shortest parent, child, and spouse path within one dataset
legacy-family-tree related genealogy.sqlite 1 100 250
```

Queries are dataset-scoped. Explicit cross-dataset identity links do not cause
tree or relationship traversal to cross dataset boundaries.

## Cross-Dataset Identity

Imports never assume that similar records represent the same person. Review
conservative suggestions, then create links explicitly:

```console
# Search every pair of datasets, or append one or two dataset IDs
legacy-family-tree suggest-links genealogy.sqlite --limit 100
legacy-family-tree suggest-links genealogy.sqlite 1 2 --limit 50

# Confirm that dataset 1/person 100 and dataset 2/person 45 are the same person
legacy-family-tree link-person genealogy.sqlite 1 100 2 45
```

Suggestions require exact normalized given name and surname plus an exact birth
or death key, and reject conflicting known vital dates. Suggestions are
read-only and are never applied automatically. Confirm links from source
evidence: `link-person` writes an identity group and can merge existing groups,
but does not merge or rewrite imported genealogy rows.

## Local Browser And Privacy

```console
legacy-family-tree browse genealogy.sqlite
```

The browser opens `http://127.0.0.1:8765/`, serves packaged static files, and
opens the SQLite database in read-only/query-only mode. It has no cloud service,
analytics, or upload step; data stays on the machine unless you deliberately
copy an output or expose the HTTP server. `--no-browser` suppresses automatic
browser launch, and `--port` changes the port.

The people index opens immediately without requiring a search. It retrieves 100
alphabetically sorted people at a time and provides Previous/Next controls, so
large trees do not create tens of thousands of browser elements. Name search
remains available and includes alternate names.

The static browser can also open a descriptive SQLite database directly,
without running the Python server. Open
`src/legacy_family_tree_reader/static/index.html` in a browser, choose **Open
SQLite file**, and select the generated database. The bundled SQL.js reader
loads it read-only into browser memory; it does not upload the file or use an
API. The Python server mode is preferable for very large databases because
direct mode holds the complete SQLite file in memory.

If the page reports that it cannot connect, either choose a SQLite file in
direct mode or make sure the `legacy-family-tree browse ...` process is still
running and open the exact URL printed in that terminal. Opening a stale
`http://127.0.0.1:8765/` tab after stopping the process cannot work.

The default loopback host is local-only. Changing `--host` to `0.0.0.0`, `::`,
or another network interface exposes unencrypted genealogy data to that
network; the server provides no authentication or TLS. Treat imported
databases and exports as private files. Browsing does not alter the database,
but `link-person` and `suggest-links` create identity metadata tables.

## Export

```console
# Export all datasets, or put a dataset ID after the output path
legacy-family-tree export-gedcom genealogy.sqlite tree.ged
legacy-family-tree export-gedcom genealogy.sqlite dataset-1.ged 1
legacy-family-tree export-excel genealogy.sqlite research.xlsx
legacy-family-tree export-excel genealogy.sqlite dataset-1.xlsx 1

# Omit people marked private or living and dependent records
legacy-family-tree export-gedcom genealogy.sqlite public.ged 1 --exclude-private
legacy-family-tree export-excel genealogy.sqlite public.xlsx 1 --exclude-private
```

GEDCOM output is UTF-8 GEDCOM 5.5.1 and includes people, families, supported
events, sources, citations, and media references. Excel output contains Data
Sets, People, Families, Parent Child, Facts and Notes, Events, Sources,
Citations, Media, and Locations worksheets. Both formats include private and
living records by default. `--exclude-private` is a convenience filter, not a
guarantee of anonymization; inspect an export before sharing it.

Legacy stores some qualified and ranged dates in packed forms that cannot be
decoded safely without more vendor metadata. Queries decode only unambiguous
dates. GEDCOM export preserves unsupported dates as notes rather than guessing.
See [docs/SCHEMA.md](docs/SCHEMA.md#dates) for details.

## Command Overview

| Command | Purpose |
| --- | --- |
| `import SOURCE OUTPUT` | Import one FDB/MDB or raw SQLite source as an isolated dataset. |
| `merge OUTPUT SOURCE...` | Import multiple isolated datasets into one descriptive SQLite database. |
| `mdb2sqlite OUTPUT SOURCE...` | Append Access sources into a raw `tbl*` compatibility database. |
| `browse DB` | Run the local read-only browser. |
| `search DB DATASET QUERY` | Search primary and alternate person names. |
| `person DB DATASET PERSON_ID` | Show identity and basic person fields. |
| `family DB DATASET PERSON_ID` | Show immediate family. |
| `facts DB DATASET PERSON_ID` | Show person fields and attached facts, events, citations, media, and research records. |
| `ancestors DB DATASET PERSON_ID` | Traverse ancestors to `--depth` generations. |
| `descendants DB DATASET PERSON_ID` | Traverse descendants to `--depth` generations. |
| `related DB DATASET PERSON_A PERSON_B` | Find a shortest relationship path. |
| `datasets DB` | List imported datasets, hashes, formats, and provenance. |
| `suggest-links DB [DATASET...]` | Suggest matches across all datasets or at most two selected datasets. |
| `link-person DB DATASET_A PERSON_A DATASET_B PERSON_B` | Record an explicit cross-dataset identity link. |
| `export-gedcom DB OUTPUT [DATASET]` | Export GEDCOM 5.5.1. |
| `export-excel DB OUTPUT [DATASET]` | Export an Excel workbook. |
| `schema` | Print supported Legacy version, mapped tables, columns, types, and descriptions as JSON. |
| `build-mdbtools` | Build and install upstream `mdbtools` with Clang/LLVM. |

Run `legacy-family-tree COMMAND --help` for command-specific options. The
standalone `mdb2sqlite` entry point and `legacy-family-tree mdb2sqlite` are
equivalent.

## Architecture

- `importer.py` validates source signatures, hashes files, streams Access rows
  through `mdb-export`, and transactionally writes descriptive or raw SQLite.
- `schema.py` is the authoritative catalog for 38 Legacy 9 tables and 522
  columns. It creates metadata tables, indexes, and summary views.
- `queries.py` opens databases read-only and implements name, person, fact,
  family, tree, and relationship JSON queries.
- `identity.py` stores explicit identity groups separately from source records
  and computes conservative suggestions.
- `server.py` exposes the read-only query layer and packaged browser assets over
  a local HTTP server.
- `static/standalone.js` uses the bundled SQL.js runtime for a direct,
  API-free local-file mode.
- `exporters.py` produces GEDCOM 5.5.1 and query-friendly Excel workbooks.
- `build_tools.py` and `scripts/build-mdbtools-llvm.sh` provide the LLVM
  `mdbtools` build path.

The descriptive database is ordinary SQLite and can be queried directly. Join
source entities on both `dataset_id` and their descriptive entity ID. The
`people`, `families`, `marriage_summary`, `event_summary`, `citation_summary`,
and `media_summary` views cover common exploration tasks. Full schema and
polymorphic relationship details are in [docs/SCHEMA.md](docs/SCHEMA.md).

## Troubleshooting

**`mdb-tables is required` or `mdb-export is required`**

Confirm both commands are on `PATH`. If the LLVM builder installed to the
default prefix, add `~/.local/bin` to `PATH` in your shell environment.

**`mdbtools` fails on a Legacy file**

Work from a copy, confirm the file is an FDB/MDB family database, and try a
current upstream `mdbtools` build with `legacy-family-tree build-mdbtools`.
Password-protected, damaged, or unsupported Access files may not be readable.

**`mdb-count` disagrees with the imported row count**

`mdb-count` can disagree with exportable rows for some Access files. The
importer does not trust that count: it parses the complete CSV record stream
from `mdb-export`, handles quoted/multiline fields, and validates that the
`mdb-export` process completes successfully. Diagnose discrepancies against the
export stream rather than treating `mdb-count` as authoritative.

**Duplicate SHA-256 error**

The exact source bytes were already imported. Use `legacy-family-tree datasets`
to locate the existing dataset. Use `--allow-duplicate` only when a second,
intentionally identical dataset is required.

**No Legacy 9 tables found**

The source must expose recognized Legacy 9 `tbl*` tables. A general SQLite
database, an already descriptive output database, or an HDB history file is not
a raw import source.

**A date is still numeric or appears as `Legacy date:` in GEDCOM**

That date contains an unsupported qualifier, range, flags, sentinel, or invalid
calendar components. The raw value is retained intentionally; do not infer a
calendar date from a sort key without checking the source.

**Browser cannot be reached**

Check the URL printed by the command, choose another port with `--port`, and
leave `--host` at `127.0.0.1` unless network access is explicitly intended.

## Contributing

Create a checkout, then synchronize the locked project environment:

```console
git clone https://github.com/isaiahpettingill/LegacyFamilyTreeReaderScripts
cd LegacyFamilyTreeReaderScripts
uv sync
uv run ruff check .
uv run pytest
```

Use `uv add PACKAGE` for runtime dependency changes and
`uv add --dev PACKAGE` for development dependency changes. Do not use `uv pip`
or `pip`; dependency declarations and `uv.lock` must remain synchronized.

Do not commit private genealogy fixtures. Tests and documentation must use
synthetic, generic records.

## License

Legacy Family Tree Reader Scripts is licensed under the GNU General Public
License, version 2 only. See [LICENSE](LICENSE).

The browser bundles SQL.js 1.13.0 under its MIT license. See
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) and the license distributed
with the browser assets.
