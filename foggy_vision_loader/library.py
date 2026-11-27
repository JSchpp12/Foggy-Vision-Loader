"""Read-only library facade for a FoggyVision database."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from types import TracebackType
from typing import Optional, Type

from .records import DISTANCE_METRICS, ImageRecord
from .selection import Selection, _build_catalog_sql

DATABASE_FILE_NAME = "database.sqlite3"
DATABASE_ENV = "FOGGY_VISION_DATABASE"

_REQUIRED_COLUMNS = {
    "image": {"id", "fileName", "fileType", "width", "height"},
    "view": {"id", "colorImageID", "cameraID", "sceneID", "environmentID"},
    "scene": {"id", "name", "terrainRenderingType", "coverageDistanceMiles"},
    "camera": {"id", "virtualPosition", "lookDir"},
    "environment": {"id", "fogID"},
    "fog": {
        "id",
        "typeID",
        "volumeName",
        "expFogDensity",
        "marchedDensityMultiplier",
    },
    "fog_type": {"id", "name"},
    "visibility_distance": {
        "viewID",
        "distanceType",
        "value",
        "average",
        "median",
        "minimum",
        "rayCount",
    },
    "view_image": {"viewID", "imageID", "role"},
}


class FoggyVisionSchemaError(ValueError):
    """Raised when a SQLite file is not a FoggyVision database."""


class FoggyVisionLibrary:
    """Query facade over a FoggyVision ``database.sqlite3`` file.

    ``db_path`` must be the SQLite database file itself (a directory is
    rejected).  ``images_dir`` defaults to the ``images`` directory next to the
    database and is the root of every ``ImageRecord.path``.

    This facade opens the database read-only and never writes to it.  Build or
    rebuild a dataset with the package's ``fogvis-cli`` command (see
    :mod:`foggy_vision_loader.data_importer`).
    """

    def __init__(
        self,
        db_path: Path | str | None = None,
        *,
        images_dir: Path | str | None = None,
    ) -> None:
        if db_path is None:
            db_path = _environment_database_path()
        resolved = Path(db_path).expanduser()
        if resolved.is_dir():
            raise ValueError(
                "expected the database.sqlite3 file, got a directory: "
                f"{resolved}; pass {resolved / DATABASE_FILE_NAME}"
            )
        database = resolved.resolve()
        if not database.is_file():
            raise FileNotFoundError(f"FoggyVision database not found: {database}")

        self._db_path = database
        self._db_dir = database.parent
        if images_dir is not None:
            self._data_dir = Path(images_dir).expanduser().resolve()
        else:
            self._data_dir = self._db_dir / "images"
        self._conn: Optional[sqlite3.Connection] = None
        self._has_skybox = False
        self.catalog_sql = _build_catalog_sql(False)
        # Fail fast: opening the read-only connection also validates the schema.
        self._conn = self._connect()

    # ------------------------------------------------------------- locations

    @property
    def db_path(self) -> Path:
        """Path to ``database.sqlite3``."""
        return self._db_path

    @property
    def db_dir(self) -> Path:
        """Directory containing the database."""
        return self._db_dir

    @property
    def data_dir(self) -> Path:
        """Image root; ``data_dir / record.path`` is the image file."""
        return self._data_dir

    @property
    def images_dir(self) -> Path:
        """Alias of :attr:`data_dir`."""
        return self._data_dir

    @property
    def conn(self) -> sqlite3.Connection:
        """The read-only SQLite connection (reopened after :meth:`close`)."""
        if self._conn is None:
            self._conn = self._connect()
        return self._conn

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self._db_path.as_uri() + "?mode=ro", uri=True
        )
        connection.row_factory = sqlite3.Row
        try:
            _validate_schema(connection)
            self._has_skybox = _detect_skybox(connection)
            self.catalog_sql = _build_catalog_sql(self._has_skybox)
        except Exception:
            connection.close()
            raise
        return connection

    # ---------------------------------------------------------------- queries

    def query(self) -> Selection:
        """Start a new composable selection."""
        return Selection(library=self)

    def stats(self) -> dict:
        query = self.query()
        connection = self.conn
        sessions = self.sessions()
        return {
            "db_path": str(self.db_path),
            "db_dir": str(self.db_dir),
            "data_dir": str(self.data_dir),
            "color_images": query.count(),
            "views": int(
                connection.execute("SELECT COUNT(*) FROM view").fetchone()[0]
            ),
            "sessions": len(sessions),
            "scenes": len(self.scenes()),
            "fog_types": len(self.fog_types()),
            "skyboxes": len(self.skyboxes()),
            "images_with_visibility": query.has_visibility(True).count(),
            "images_with_masks": query.has_masks(True).count(),
            "simple_metric": query.visibility_metric("simple").count(),
            "ray_excluding_metric": query.visibility_metric(
                "ray_excluding_invalid"
            ).count(),
            "ray_including_metric": query.visibility_metric(
                "ray_including_invalid"
            ).count(),
            "earliest_session": sessions[0] if sessions else None,
            "latest_session": sessions[-1] if sessions else None,
        }

    def sessions(self) -> list[str]:
        return sorted(
            key for key in self.query().counts_by("session") if key is not None
        )

    def scenes(self) -> list[str]:
        return sorted(
            key for key in self.query().counts_by("scene") if key is not None
        )

    def fog_types(self) -> list[str]:
        return sorted(
            key for key in self.query().counts_by("fog_type") if key is not None
        )

    def skyboxes(self) -> list[str]:
        """Skybox names recorded in the database; empty for legacy databases."""
        return sorted(
            key for key in self.query().counts_by("skybox") if key is not None
        )

    # ------------------------------------------------------------ path helpers

    def absolute_path(self, record_or_path: ImageRecord | str) -> Path:
        path = record_or_path.path if isinstance(record_or_path, ImageRecord) else str(
            record_or_path
        )
        return self.data_dir / path

    def mask_paths(self, record: ImageRecord) -> dict[str, Path]:
        return {
            role: self.data_dir / path for role, path in record.mask_paths.items()
        }

    # -------------------------------------------------------------- lifecycle

    def close(self) -> None:
        """Close the read-only connection; safe to call more than once."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "FoggyVisionLibrary":
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        self.close()

    @classmethod
    def open(
        cls,
        db_path: Path | str | None = None,
        *,
        images_dir: Path | str | None = None,
    ) -> "FoggyVisionLibrary":
        """Constructor alias, mirroring ``AirViewLibrary.open``."""
        return cls(db_path, images_dir=images_dir)


def _environment_database_path() -> str:
    value = os.environ.get(DATABASE_ENV)
    if value:
        return value
    raise ValueError(
        "no database given; pass the database.sqlite3 file or set "
        f"{DATABASE_ENV}"
    )


def _detect_skybox(connection: sqlite3.Connection) -> bool:
    """Whether the database records skybox metadata on views.

    Both the table and the ``view.skyboxID`` column are required; a partially
    migrated schema falls back to the legacy catalog shape instead of raising.
    """
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    if "skybox" not in tables:
        return False
    columns = {row[1] for row in connection.execute("PRAGMA table_info(view)")}
    return "skyboxID" in columns


def _validate_schema(connection: sqlite3.Connection) -> None:
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    missing_tables = sorted(set(_REQUIRED_COLUMNS) - tables)
    if missing_tables:
        raise FoggyVisionSchemaError(
            "not a FoggyVision database (missing tables: "
            f"{', '.join(missing_tables)}); build one with 'fogvis-cli import' "
            "from foggy_vision_loader"
        )
    for table, required in _REQUIRED_COLUMNS.items():
        present = {
            row[1] for row in connection.execute(f"PRAGMA table_info({table})")
        }
        missing = sorted(required - present)
        if missing:
            raise FoggyVisionSchemaError(
                f"FoggyVision table {table!r} is missing columns: "
                f"{', '.join(missing)}"
            )


__all__ = [
    "DATABASE_ENV",
    "DATABASE_FILE_NAME",
    "DISTANCE_METRICS",
    "FoggyVisionLibrary",
    "FoggyVisionSchemaError",
    "ImageRecord",
    "Selection",
]
