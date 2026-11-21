"""Read-only query and selection library for the FoggyVision dataset.

The package depends only on the Python standard library.  It reads a database
produced by the FoggyVision project's ``fogvis-cli import`` command and exposes
a fluent selection API::

    from foggy_vision_loader import FoggyVisionLibrary

    lib = FoggyVisionLibrary("media/db/database.sqlite3")
    lib.query().scene_name("berthoud").visibility(max_meters=8000).records()
"""

from .library import (
    DATABASE_ENV,
    DATABASE_FILE_NAME,
    FoggyVisionLibrary,
    FoggyVisionSchemaError,
)
from .records import (
    DISTANCE_METRICS,
    METERS_PER_MILE,
    RAY_EXCLUDING_INVALID,
    RAY_INCLUDING_INVALID,
    SIMPLE,
    ImageRecord,
)
from .selection import Selection
from .library import __version__

__all__ = [
    "DATABASE_ENV",
    "DATABASE_FILE_NAME",
    "DISTANCE_METRICS",
    "FoggyVisionLibrary",
    "FoggyVisionSchemaError",
    "ImageRecord",
    "METERS_PER_MILE",
    "RAY_EXCLUDING_INVALID",
    "RAY_INCLUDING_INVALID",
    "SIMPLE",
    "Selection",
    "__version__",
]
