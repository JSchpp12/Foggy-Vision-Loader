"""Fixture database builder for loader tests.

The DDL mirrors ``FoggyVision/src/fogvis/db/schema.py``.  Tests construct a
small database directly so the loader suite has no dependency on FoggyVision
or its heavy ML packages.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA_SQL = """
CREATE TABLE coordinate(
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    lat     REAL NOT NULL,
    lon     REAL NOT NULL
);
CREATE TABLE scene(
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    name                        TEXT NOT NULL,
    coverageDistanceMiles       REAL NOT NULL,
    upperRightPositionID        INTEGER NOT NULL REFERENCES coordinate(id),
    lowerLeftPositionID         INTEGER NOT NULL REFERENCES coordinate(id),
    centerPositionID            INTEGER NOT NULL REFERENCES coordinate(id),
    terrainRenderingType        TEXT NOT NULL,
    terrainShapeCenter          TEXT,
    UNIQUE(name, terrainRenderingType)
);
CREATE TABLE camera(
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    virtualPosition     TEXT NOT NULL,
    sceneID             INTEGER REFERENCES scene(id) NOT NULL,
    lookDir             TEXT NOT NULL,
    fov REAL,
    nearClip REAL,
    farClip REAL
);
CREATE TABLE fog_type(
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT NOT NULL
);
CREATE TABLE fog(
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    typeID                      INTEGER NOT NULL REFERENCES fog_type(id),
    sceneID                     INTEGER NOT NULL REFERENCES scene(id),
    expFogDensity               REAL,
    linearNearDistance          REAL,
    linearFarDistance           REAL,
    marchedCutoff               REAL,
    marchedColorTransparencyCutoff REAL,
    marchedDistanceTransparencyCutoff REAL,
    marchedLightExtinctionScale REAL,
    marchedDefaultDensity       REAL,
    marchedDensityMultiplier    REAL,
    marchedLightG               REAL,
    marchedSigmaAbsorption      REAL,
    marchedSigmaScattering      REAL,
    marchedStepSizeDist         REAL,
    marchedStepSizeDistLight    REAL,
    volumeName                  TEXT,
    volumePosition              TEXT,
    volumeRotation              TEXT,
    volumeScale                 TEXT
);
CREATE TABLE light_type(
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT NOT NULL
);
CREATE TABLE light(
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    ambient                 TEXT NOT NULL,
    diffuse                 TEXT NOT NULL,
    specular                TEXT NOT NULL,
    virtualDirection        TEXT NOT NULL,
    virtualPosition         TEXT NOT NULL,
    enabled                 BOOLEAN NOT NULL,
    innerDiameter           REAL NOT NULL,
    outerDiameter           REAL NOT NULL,
    luminance               INTEGER NOT NULL,
    typeID                  INTEGER NOT NULL REFERENCES light_type(id)
);
CREATE TABLE environment(
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    fogID   INTEGER NOT NULL REFERENCES fog(id)
);
CREATE TABLE environment_light(
    lightID        INTEGER NOT NULL REFERENCES light(id),
    environmentID  INTEGER NOT NULL REFERENCES environment(id)
);
CREATE TABLE image(
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    fileName    TEXT NOT NULL UNIQUE,
    fileType    TEXT NOT NULL,
    width       INTEGER,
    height      INTEGER,
    checksum    TEXT
);
CREATE TABLE view(
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    colorImageID   INTEGER NOT NULL REFERENCES image(id),
    cameraID       INTEGER NOT NULL REFERENCES camera(id),
    sceneID        INTEGER NOT NULL REFERENCES scene(id),
    environmentID  INTEGER NOT NULL REFERENCES environment(id)
);
CREATE TABLE view_image(
    viewID  INTEGER NOT NULL REFERENCES view(id),
    imageID INTEGER NOT NULL REFERENCES image(id),
    role    TEXT NOT NULL,
    PRIMARY KEY (viewID, role)
);
CREATE TABLE visibility_distance(
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    viewID        INTEGER NOT NULL REFERENCES view(id),
    distanceType  TEXT NOT NULL,
    value         REAL,
    average       REAL,
    median        REAL,
    minimum       REAL,
    rayCount      INTEGER,
    UNIQUE(viewID, distanceType)
);
CREATE INDEX idx_image_filename ON image(fileName);
"""

#: Layered on top of ``SCHEMA_SQL``; the ALTER mirrors the importer's migration
#: so the loader tests exercise the same upgrade path as a real database.
SKYBOX_SQL = """
CREATE TABLE skybox(
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);
ALTER TABLE view ADD COLUMN skyboxID INTEGER REFERENCES skybox(id);
CREATE INDEX idx_view_skybox ON view(skyboxID);
"""

MASK_FILES = {
    "ray_distance": "Frame-{n}_distMask.tif",
    "ray_normalized_distance": "Frame-{n}_distNormSmlMask.tif",
    "ray_validity": "Frame-{n}_validMask.png",
}


@dataclass
class Frame:
    """Description of one fixture color image and its linked rows."""

    session: str
    frame: int
    scene: str = "berthoud_pass_co"
    terrain_rendering_type: str = "real"
    coverage_distance_miles: float = 10.0
    fog_type: str = "marched"
    fog_volume: str = "windy_whipped"
    skybox: str | None = None
    exp_fog_density: float = 0.6
    density_multiplier: float = 1.0
    width: int = 1280
    height: int = 720
    masks: bool = True
    metrics: dict = field(default_factory=dict)


def create_schema(db_dir: Path, *, include_skybox: bool = True) -> Path:
    """Create an empty but valid FoggyVision database; return its path."""
    db_dir = Path(db_dir)
    db_dir.mkdir(parents=True, exist_ok=True)
    database = db_dir / "database.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.executescript(SCHEMA_SQL)
        if include_skybox:
            connection.executescript(SKYBOX_SQL)
    return database


def build_db(
    db_dir: Path, frames: list[Frame], *, include_skybox: bool = True
) -> Path:
    """Create ``db_dir/database.sqlite3`` and populate it; return the db path."""
    db_dir = Path(db_dir)
    db_dir.mkdir(parents=True, exist_ok=True)
    database = db_dir / "database.sqlite3"
    if database.exists():
        database.unlink()

    with sqlite3.connect(database) as connection:
        connection.executescript(SCHEMA_SQL)
        if include_skybox:
            connection.executescript(SKYBOX_SQL)
        cursor = connection.cursor()

        cursor.execute(
            "INSERT INTO coordinate (lat, lon) VALUES (?, ?)", (39.794502, -105.76389)
        )
        coordinate_id = cursor.lastrowid

        cursor.execute(
            """INSERT INTO scene (
                   name, coverageDistanceMiles, upperRightPositionID,
                   lowerLeftPositionID, centerPositionID,
                   terrainRenderingType, terrainShapeCenter
               ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                frames[0].scene,
                frames[0].coverage_distance_miles,
                coordinate_id,
                coordinate_id,
                coordinate_id,
                frames[0].terrain_rendering_type,
                '{"x": -105.76389, "y": 39.794502}',
            ),
        )
        scene_id = cursor.lastrowid

        cursor.execute(
            """INSERT INTO camera (
                   virtualPosition, sceneID, lookDir, fov, nearClip, farClip
               ) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                '{"x": 0.0, "y": 15.0, "z": 0.0}',
                scene_id,
                '{"x": 0.0, "y": 0.0, "z": 1.0}',
                60.0,
                0.1,
                20000.0,
            ),
        )
        camera_id = cursor.lastrowid

        cursor.execute("INSERT INTO fog_type (name) VALUES (?)", (frames[0].fog_type,))
        fog_type_id = cursor.lastrowid

        fog_ids: dict[str, int] = {}
        environment_ids: dict[str, int] = {}
        for frame in frames:
            if frame.fog_volume in fog_ids:
                continue
            cursor.execute(
                """INSERT INTO fog (
                       typeID, sceneID, expFogDensity, marchedDefaultDensity,
                       marchedDensityMultiplier, volumeName
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    fog_type_id,
                    scene_id,
                    frame.exp_fog_density,
                    0.0,
                    frame.density_multiplier,
                    frame.fog_volume,
                ),
            )
            fog_id = cursor.lastrowid
            fog_ids[frame.fog_volume] = fog_id
            cursor.execute(
                "INSERT INTO environment (fogID) VALUES (?)", (fog_id,)
            )
            environment_ids[frame.fog_volume] = cursor.lastrowid

        skybox_ids: dict[str, int] = {}
        if include_skybox:
            for frame in frames:
                if frame.skybox and frame.skybox not in skybox_ids:
                    cursor.execute(
                        "INSERT INTO skybox (name) VALUES (?)", (frame.skybox,)
                    )
                    skybox_ids[frame.skybox] = cursor.lastrowid

        for frame in frames:
            images_dir = db_dir / "images" / frame.session
            images_dir.mkdir(parents=True, exist_ok=True)
            color_path = f"{frame.session}/Frame-{frame.frame}.png"
            cursor.execute(
                """INSERT INTO image (fileName, fileType, width, height)
                   VALUES (?, 'color', ?, ?)""",
                (color_path, frame.width, frame.height),
            )
            color_id = cursor.lastrowid
            (db_dir / "images" / color_path).write_bytes(b"")

            if include_skybox:
                cursor.execute(
                    """INSERT INTO view (
                           colorImageID, cameraID, sceneID, environmentID, skyboxID
                       ) VALUES (?, ?, ?, ?, ?)""",
                    (
                        color_id,
                        camera_id,
                        scene_id,
                        environment_ids[frame.fog_volume],
                        skybox_ids.get(frame.skybox) if frame.skybox else None,
                    ),
                )
            else:
                cursor.execute(
                    """INSERT INTO view (
                           colorImageID, cameraID, sceneID, environmentID
                       ) VALUES (?, ?, ?, ?)""",
                    (
                        color_id,
                        camera_id,
                        scene_id,
                        environment_ids[frame.fog_volume],
                    ),
                )
            view_id = cursor.lastrowid

            if frame.masks:
                for role, template in MASK_FILES.items():
                    mask_path = f"{frame.session}/{template.format(n=frame.frame)}"
                    cursor.execute(
                        """INSERT INTO image (fileName, fileType, width, height)
                           VALUES (?, ?, ?, ?)""",
                        (mask_path, role, frame.width, frame.height),
                    )
                    cursor.execute(
                        "INSERT INTO view_image (viewID, imageID, role) VALUES (?, ?, ?)",
                        (view_id, cursor.lastrowid, role),
                    )
                    (db_dir / "images" / mask_path).write_bytes(b"")

            for distance_type, values in frame.metrics.items():
                cursor.execute(
                    """INSERT INTO visibility_distance (
                           viewID, distanceType, value, average, median, minimum,
                           rayCount
                       ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        view_id,
                        distance_type,
                        values.get("value"),
                        values.get("average"),
                        values.get("median"),
                        values.get("minimum"),
                        values.get("rayCount"),
                    ),
                )

    return database


def ray_frames() -> list[Frame]:
    """Six frames covering all three fallback cases and 4 sessions."""
    empty_excluding = {
        "average": None,
        "median": None,
        "minimum": None,
        "rayCount": 0,
    }
    return [
        Frame(
            session="2026-06-13_21-40-15",
            frame=0,
            skybox="autumn_field_puresky_4k",
            density_multiplier=1.0,
            metrics={
                "ray_including_invalid": {
                    "average": 7197.180718457964,
                    "median": 7346.66,
                    "minimum": 5198.96,
                    "rayCount": 921600,
                },
                "ray_excluding_invalid": dict(empty_excluding),
            },
        ),
        Frame(
            session="2026-06-13_21-40-15",
            frame=1,
            skybox="autumn_field_puresky_4k",
            density_multiplier=2.0,
            metrics={
                "ray_including_invalid": {
                    "average": 11000.0,
                    "median": 11000.0,
                    "minimum": 9000.0,
                    "rayCount": 921600,
                },
                "ray_excluding_invalid": dict(empty_excluding),
            },
        ),
        Frame(
            session="2026-06-13_21-45-51",
            frame=8,
            skybox="autumn_field_puresky_4k",
            density_multiplier=9.0,
            metrics={
                "ray_including_invalid": dict(empty_excluding),
                "ray_excluding_invalid": {
                    "average": 23999.276329627402,
                    "median": 24000.0,
                    "minimum": 20000.0,
                    "rayCount": 52,
                },
            },
        ),
        Frame(
            session="2026-06-13_21-45-51",
            frame=9,
            skybox="cloudy_sky",
            density_multiplier=10.0,
            masks=False,
            metrics={
                "ray_including_invalid": dict(empty_excluding),
                "ray_excluding_invalid": {
                    "average": 10459.746687819246,
                    "median": 10500.0,
                    "minimum": 8000.0,
                    "rayCount": 3891,
                },
            },
        ),
        Frame(
            session="2026-06-13_22-01-00",
            frame=0,
            fog_volume="clouds",
            skybox="cloudy_sky",
            density_multiplier=1.0,
            metrics={
                "simple": {"value": 5000.0},
                "ray_including_invalid": {
                    "average": 20735.01779993905,
                    "median": 21000.0,
                    "minimum": 18000.0,
                    "rayCount": 921600,
                },
            },
        ),
        Frame(
            session="2026-06-14_08-00-00",
            frame=0,
            fog_volume="clouds",
            density_multiplier=2.0,
            metrics={
                "ray_including_invalid": {
                    "average": 15000.0,
                    "median": 15500.0,
                    "minimum": 12000.0,
                    "rayCount": 921600,
                },
                "ray_excluding_invalid": {
                    "average": 12000.0,
                    "median": 12200.0,
                    "minimum": 10000.0,
                    "rayCount": 900000,
                },
            },
        ),
    ]


def new_format_frames() -> list[Frame]:
    """Frames whose session folders use milliseconds and a PID suffix."""
    return [
        Frame(
            session="2026-11-21_14-57-24-314_pid38604",
            frame=0,
            skybox="autumn_field_puresky_4k",
            metrics={"simple": {"value": 1000.0}},
        ),
        Frame(
            session="2026-11-21_14-57-24-314_pid38604",
            frame=1,
            skybox="autumn_field_puresky_4k",
            metrics={"simple": {"value": 2000.0}},
        ),
        Frame(
            session="2026-11-21_14-57-25-001_pid38605",
            frame=0,
            skybox="cloudy_sky",
            metrics={"simple": {"value": 3000.0}},
        ),
        Frame(
            session="2026-11-21_14-57-25-999_pid38605",
            frame=1,
            skybox="cloudy_sky",
            metrics={"simple": {"value": 4000.0}},
        ),
    ]


def simple_frames() -> list[Frame]:
    """Two frames whose only metric is ``simple``."""
    return [
        Frame(
            session="2026-06-14_11-19-33",
            frame=0,
            metrics={"simple": {"value": 1000.0}},
        ),
        Frame(
            session="2026-06-14_11-19-33",
            frame=1,
            metrics={"simple": {"value": 2666.66650390625}},
        ),
    ]
