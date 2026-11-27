from __future__ import annotations

from pathlib import Path

import pytest

from foggy_vision_loader import FoggyVisionLibrary

from .helpers import build_db, new_format_frames, ray_frames, simple_frames


MEDIA_TEST_DIR = Path(__file__).resolve().parent.parent / "media" / "test"
SAMPLE_DATE_DIRS = sorted(MEDIA_TEST_DIR.iterdir())


@pytest.fixture
def sample_json_path() -> Path:
    """Path to a single sample Frame-0.json file."""
    return SAMPLE_DATE_DIRS[0] / "Frame-0.json"


@pytest.fixture
def sample_json_paths() -> list[Path]:
    """Paths to all sample frame JSON files."""
    paths: list[Path] = []
    for date_dir in SAMPLE_DATE_DIRS:
        paths.extend(sorted(date_dir.glob("Frame-*.json")))
    return paths


@pytest.fixture
def ray_db(tmp_path):
    return build_db(tmp_path / "ray_db", ray_frames())


@pytest.fixture
def simple_db(tmp_path):
    return build_db(tmp_path / "simple_db", simple_frames())


@pytest.fixture
def ray_lib(ray_db):
    library = FoggyVisionLibrary(ray_db)
    yield library
    library.close()


@pytest.fixture
def simple_lib(simple_db):
    library = FoggyVisionLibrary(simple_db)
    yield library
    library.close()


@pytest.fixture
def new_format_db(tmp_path):
    return build_db(tmp_path / "new_format_db", new_format_frames())


@pytest.fixture
def new_format_lib(new_format_db):
    library = FoggyVisionLibrary(new_format_db)
    yield library
    library.close()


@pytest.fixture
def legacy_db(tmp_path):
    return build_db(tmp_path / "legacy_db", ray_frames(), include_skybox=False)


@pytest.fixture
def legacy_lib(legacy_db):
    library = FoggyVisionLibrary(legacy_db)
    yield library
    library.close()
