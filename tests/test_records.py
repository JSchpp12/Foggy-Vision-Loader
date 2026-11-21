from __future__ import annotations

from datetime import datetime, timezone

import pytest

from foggy_vision_loader import (
    METERS_PER_MILE,
    RAY_EXCLUDING_INVALID,
    RAY_INCLUDING_INVALID,
    SIMPLE,
    ImageRecord,
)


def test_visibility_miles_conversion(ray_lib):
    record = (
        ray_lib.query()
        .where("path = ?", ("2026-06-13_21-40-15/Frame-0.png",))
        .first()
    )
    assert record.visibility_meters == record.visibility_value
    assert record.visibility_miles == pytest.approx(
        7197.180718457964 / METERS_PER_MILE
    )


def test_visibility_by_metric(ray_lib):
    record = (
        ray_lib.query()
        .where("path = ?", ("2026-06-13_21-45-51/Frame-8.png",))
        .first()
    )
    assert record.visibility_by_metric == {
        SIMPLE: None,
        RAY_INCLUDING_INVALID: None,
        RAY_EXCLUDING_INVALID: 23999.276329627402,
    }


def test_mask_paths_omits_missing(ray_lib):
    record = (
        ray_lib.query()
        .where("path = ?", ("2026-06-13_21-45-51/Frame-9.png",))
        .first()
    )
    assert record.mask_paths == {}


def test_all_masks_present(ray_lib):
    record = ray_lib.query().has_masks(True).first()
    assert set(record.mask_paths) == {
        "ray_distance",
        "ray_normalized_distance",
        "ray_validity",
    }


def test_null_visibility_properties():
    record = ImageRecord(
        path="session/Frame-0.png",
        format="color",
        width=1280,
        height=720,
        session="2024-01-02_03-04-05",
        captured_at=datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
    )
    assert record.visibility_value is None
    assert record.visibility_meters is None
    assert record.visibility_miles is None
    assert record.visibility_metric is None
    assert record.visibility_by_metric == {
        SIMPLE: None,
        RAY_INCLUDING_INVALID: None,
        RAY_EXCLUDING_INVALID: None,
    }
    assert record.mask_paths == {}
