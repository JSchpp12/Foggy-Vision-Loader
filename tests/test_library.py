from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

import foggy_vision_loader
from foggy_vision_loader import (
    DATABASE_ENV,
    FoggyVisionLibrary,
    FoggyVisionSchemaError,
)

from .helpers import create_schema


def test_directory_input_is_rejected(ray_db):
    with pytest.raises(ValueError, match="database.sqlite3"):
        FoggyVisionLibrary(ray_db.parent)


def test_constructor_accepts_file(ray_db):
    lib = FoggyVisionLibrary(ray_db)
    assert lib.db_path == ray_db
    assert lib.db_dir == ray_db.parent
    assert lib.data_dir == ray_db.parent / "images"
    assert lib.images_dir == lib.data_dir
    assert lib.query().count() == 6
    lib.close()


def test_images_dir_override(ray_db, tmp_path):
    other = tmp_path / "other_images"
    lib = FoggyVisionLibrary(ray_db, images_dir=other)
    assert lib.data_dir == other.resolve()
    lib.close()


def test_missing_database_raises_and_does_not_create(tmp_path):
    missing = tmp_path / "nope"
    with pytest.raises(FileNotFoundError):
        FoggyVisionLibrary(missing)
    assert not missing.exists()


def test_env_fallback_database(ray_db, monkeypatch):
    monkeypatch.setenv(DATABASE_ENV, str(ray_db))
    lib = FoggyVisionLibrary()
    assert lib.db_path == ray_db
    assert lib.query().count() == 6
    lib.close()


def test_legacy_env_vars_are_ignored(ray_db, monkeypatch):
    monkeypatch.delenv(DATABASE_ENV, raising=False)
    monkeypatch.setenv("FOGGY_VISION_DB", str(ray_db))
    monkeypatch.setenv("FOGGY_VISION_DATA_DIR", str(ray_db.parent))
    with pytest.raises(ValueError):
        FoggyVisionLibrary()


def test_no_env_raises(monkeypatch):
    monkeypatch.delenv(DATABASE_ENV, raising=False)
    with pytest.raises(ValueError):
        FoggyVisionLibrary()


def test_open_classmethod(ray_db):
    with FoggyVisionLibrary.open(ray_db) as lib:
        assert lib.query().count() == 6


def test_non_foggyvision_database_raises(tmp_path):
    empty = tmp_path / "empty.sqlite3"
    sqlite3.connect(empty).close()
    with pytest.raises(FoggyVisionSchemaError, match="missing tables"):
        FoggyVisionLibrary(empty)


def test_missing_column_raises(tmp_path):
    db = create_schema(tmp_path / "bad_schema")
    with sqlite3.connect(db) as connection:
        connection.execute("ALTER TABLE image DROP COLUMN fileType")
    with pytest.raises(FoggyVisionSchemaError, match="fileType"):
        FoggyVisionLibrary(db)


def test_valid_empty_database(tmp_path):
    db = create_schema(tmp_path / "empty_db")
    with FoggyVisionLibrary(db) as lib:
        assert lib.query().count() == 0
        assert lib.query().records() == []
        assert lib.query().first() is None
        stats = lib.stats()
        assert stats["color_images"] == 0
        assert stats["views"] == 0
        assert stats["skyboxes"] == 0
        assert stats["earliest_session"] is None


def test_connection_is_read_only(ray_db):
    with FoggyVisionLibrary(ray_db) as lib:
        with pytest.raises(sqlite3.OperationalError):
            lib.conn.execute("CREATE TABLE forbidden (id INTEGER)")


def test_close_is_idempotent_and_reopens_lazily(ray_db):
    lib = FoggyVisionLibrary(ray_db)
    assert lib.query().count() == 6
    lib.close()
    lib.close()
    assert lib.query().count() == 6
    lib.close()


def test_stats(ray_lib):
    stats = ray_lib.stats()
    assert stats["color_images"] == 6
    assert stats["views"] == 6
    assert stats["sessions"] == 4
    assert stats["scenes"] == 1
    assert stats["fog_types"] == 1
    assert stats["skyboxes"] == 2
    assert stats["images_with_visibility"] == 6
    assert stats["images_with_masks"] == 5
    assert stats["simple_metric"] == 1
    assert stats["ray_including_metric"] == 4
    assert stats["ray_excluding_metric"] == 3
    assert stats["earliest_session"] == "2026-06-13_21-40-15"
    assert stats["latest_session"] == "2026-06-14_08-00-00"


def test_sessions_scenes_fog_types(ray_lib):
    assert ray_lib.sessions() == [
        "2026-06-13_21-40-15",
        "2026-06-13_21-45-51",
        "2026-06-13_22-01-00",
        "2026-06-14_08-00-00",
    ]
    assert ray_lib.scenes() == ["berthoud_pass_co"]
    assert ray_lib.fog_types() == ["marched"]
    assert ray_lib.skyboxes() == ["autumn_field_puresky_4k", "cloudy_sky"]


def test_absolute_path_and_mask_paths(ray_lib):
    record = ray_lib.query().scene_name("berthoud_pass_co", exact=True).first()
    assert ray_lib.absolute_path(record).exists()
    assert ray_lib.absolute_path(record.path) == ray_lib.absolute_path(record)
    masks = ray_lib.mask_paths(record)
    assert set(masks) == {
        "ray_distance",
        "ray_normalized_distance",
        "ray_validity",
    }
    assert all(path.exists() for path in masks.values())


def test_stats_new_session_format(new_format_lib):
    stats = new_format_lib.stats()
    assert stats["sessions"] == 3
    assert stats["earliest_session"] == "2026-11-21_14-57-24-314_pid38604"
    assert stats["latest_session"] == "2026-11-21_14-57-25-999_pid38605"


def test_public_exports_and_version():
    assert foggy_vision_loader.__version__ == "0.3.0"
    for name in ("FoggyVisionLibrary", "Selection", "ImageRecord"):
        assert hasattr(foggy_vision_loader, name)


def test_public_api_imports_no_heavy_dependencies():
    repo_root = Path(__file__).resolve().parent.parent
    code = (
        "import sys; import foggy_vision_loader; "
        "heavy = [m for m in ('torch', 'numpy', 'PIL', 'cv2', 'matplotlib', "
        "'scipy') if m in sys.modules]; print(heavy)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "[]"
