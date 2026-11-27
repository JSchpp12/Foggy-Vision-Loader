# foggy_vision_loader

Import, query, and selection library for the FoggyVision synthetic fog image
corpus.

`foggy_vision_loader` owns the dataset database layer. Its `fogvis-cli`
command imports rendered frames and their JSON sidecars into a SQLite database
and can clean up or rebuild it; the query layer then serves composable
selections from that database. The query facade opens the database read-only,
no query index is built, and querying has no third-party dependencies. Importing
uses Pillow (image dimensions) and tqdm (progress), and requires Python 3.10+.

## Install

```powershell
python -m pip install -e F:\repos\Foggy_Vision_Loader
```

## Importing

```powershell
# Small bundled sample (3 sessions, 6 frames)
fogvis-cli import --database media/db --images media/test

# A rendered session directory (80 frames, ~400 MB copied)
fogvis-cli import --database media/db --images F:\repos\2026-11-08_14-05-50

# Remove orphaned image files on disk (no database rows are modified)
fogvis-cli cleanup --database media/db

# Wipe and rebuild the database from the existing images directory
fogvis-cli rebuild --database media/db
```

`--database` is the database **directory**: the importer creates
`database.sqlite3` and `images/` inside it. The loader and viewer, by contrast,
take the `database.sqlite3` **file** itself.

The importer accepts both JSON layouts used by the renderer (`image_files` /
`distance_mask_images` wrappers and the older flat `file_name` / `ray_masks`
keys). When a frame JSON contains a `skybox_info` block, its `name` is stored
per view in the `skybox` table and linked from `view.skyboxID`; older frame
JSONs without the block import as `NULL`. Importing into an existing database
adds the new table/column in place, but only `fogvis-cli rebuild` re-reads the
preserved Frame JSON sidecars and backfills skybox names for old views.

## Dataset layout

```
<db_dir>/
├── database.sqlite3
└── images/
    └── 2026-06-13_21-40-15/
        ├── Frame-0.png
        ├── Frame-0.json
        ├── Frame-0_distMask.tif
        ├── Frame-0_distNormSmlMask.tif
        └── Frame-0_validMask.png
```

`FoggyVisionLibrary(db_file)` takes the `database.sqlite3` file itself; a
directory argument is rejected with a message showing the expected file path.
`library.db_dir` is the file's parent, and `record.path` is POSIX-relative to
`library.data_dir` (the sibling `images/` directory by default), so
`library.data_dir / record.path` is the image file. Session folders supply
`record.session` and `record.captured_at`. Both formats are recognised:

- `YYYY-MM-DD_HH-MM-SS/` (legacy)
- `YYYY-MM-DD_HH-MM-SS-<millis>_pid<pid>/` (current; milliseconds are
  preserved in `captured_at`, and the PID is part of `record.session`)

## Usage

```python
from foggy_vision_loader import FoggyVisionLibrary

lib = FoggyVisionLibrary("F:/data/foggyvision/database.sqlite3")
print(lib.stats())
print(lib.sessions(), lib.scenes(), lib.fog_types(), lib.skyboxes())

q = lib.query()

q.count()                                        # color images
q.scene_name("berthoud").count()                 # substring, case-insensitive
q.scene_name("berthoud_pass_co", exact=True)     # exact name
q.terrain("real").count()                        # rendering type
q.fog_type("marched").count()
q.fog_volume("clouds").count()
q.skybox("autumn_field_puresky_4k").count()       # per-view skybox name
q.exp_fog_density(min=0.5, max=0.7).count()
q.sessions("2026-06-13_21-40-15").count()
q.date_range("2026-06-13", "2026-06-14").count() # inclusive, session-based
q.visibility(min_meters=3000, max_meters=12000).count()
q.visibility_metric("simple").count()            # records with a simple value
q.has_visibility(False).count()
q.has_masks(False).count()

# Composition; every filter returns a new immutable Selection
foggy = (
    lib.query()
    .scene_name("berthoud")
    .fog_type("marched")
    .fog_volume("clouds")
    .skybox("autumn_field_puresky_4k")
    .visibility(max_meters=8000)
    .order_by("visibility_value")
)

foggy.count()                                    # ignores order/limit
foggy.counts_by("session")
foggy.counts_by("metric")
foggy.limit(20).records()
foggy.limit(20).paths()                          # relative to data_dir
foggy.limit(20).absolute_paths()
foggy.first()

# Escape hatch over the normalized catalog columns
q.where("width = ? AND height = ?", (1280, 720)).count()

# Path helpers for viewers
record = foggy.first()
lib.absolute_path(record)
lib.mask_paths(record)                           # role -> absolute Path
lib.close()
```

Every filter returns a new `Selection`; only terminals (`count`, `records`,
`iter_records`, `paths`, `absolute_paths`, `first`, `counts_by`) execute SQL.
`order_by()` accepts a whitelist of record fields (`path`, `captured_at`,
`visibility_value`, `scene_name`, `fog_type`, `skybox`, ...), while `where()` is
a raw SQL escape hatch over the catalog columns.

## Skybox

Each record exposes `skybox_name` (the renderer's `skybox_info.name`), and
`q.skybox("name")` filters case-insensitively. Databases created before skybox
metadata existed still open normally: `skybox_name` is `None`,
`counts_by("skybox")` returns `{None: n}`, `skybox(...)` matches zero rows, and
`lib.skyboxes()` returns `[]`. Rebuild a dataset with `fogvis-cli rebuild` to
backfill skybox names from the preserved Frame JSON sidecars.

## Visibility metrics

Each view stores up to three `visibility_distance` rows:

| `distanceType` | fields |
|---|---|
| `simple` | `value` |
| `ray_including_invalid` | `average`, `median`, `minimum`, `rayCount` |
| `ray_excluding_invalid` | `average`, `median`, `minimum`, `rayCount` |

`record.visibility_value` uses the first available metric in the order
`simple` → `ray_including_invalid` → `ray_excluding_invalid`, and
`record.visibility_metric` names the one used. The raw values are exposed on
the record (`simple_value`, `ray_including_average`, ...). Values are in the
renderer's world units, treated as meters; `visibility_miles` uses 1609.344.

Current corpora frequently lack `simple` rows, so the ray-metric fallback
supplies most labels. A metric row whose statistics are all `NULL` (for
example `ray_excluding_invalid` with `rayCount = 0`) is exposed on the record
but does not satisfy `visibility_metric(...)` or the auto-fallback.

## Masks

`record.mask_paths` maps the three sidecar roles to relative paths:
`ray_distance` (`*_distMask.tif`), `ray_normalized_distance`
(`*_distNormSmlMask.tif`), and `ray_validity` (`*_validMask.png`). The
ray-distance TIFF is 32-bit float; normalize it before 8-bit display.

## Configuration

`FoggyVisionLibrary()` with no argument reads `FOGGY_VISION_DATABASE`, which
must point at the `.sqlite3` file (not a directory). Pass `images_dir=` when
the image tree is not the sibling `images/` directory.

## Notes

- One record is returned per color image. If a database ever has multiple
  views for one image, the library uses the lowest `view.id`.
- Session folder names carry no timezone; `captured_at` treats them as UTC.
  Millisecond/PID session folders are parsed with millisecond precision; the
  full folder name, including `_pid<pid>`, is exposed as `record.session`.
  Legacy flat filenames without a `YYYY-MM-DD_HH-MM-SS/` prefix have a `None`
  session and are excluded by `date_range()`. `date_range()` compares at
  second granularity, so a bound includes every millisecond in that second.
- `FoggyVisionLibrary` never writes to the database. Build or rebuild a
  dataset with this package's `fogvis-cli import` / `fogvis-cli rebuild`.
