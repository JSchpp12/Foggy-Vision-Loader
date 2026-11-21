from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from foggy_vision_loader import (
    RAY_EXCLUDING_INVALID,
    RAY_INCLUDING_INVALID,
    SIMPLE,
)

FRAME_0 = "2026-06-13_21-40-15/Frame-0.png"


def test_one_record_per_color_image(ray_lib):
    records = ray_lib.query().records()
    assert len(records) == 6
    assert {record.format for record in records} == {"color"}
    assert len({record.path for record in records}) == 6


def test_record_metadata(ray_lib):
    record = ray_lib.query().where("path = ?", (FRAME_0,)).first()
    assert record is not None
    assert record.path == FRAME_0
    assert record.format == "color"
    assert (record.width, record.height) == (1280, 720)
    assert record.session == "2026-06-13_21-40-15"
    assert record.captured_at == datetime(
        2026, 6, 13, 21, 40, 15, tzinfo=timezone.utc
    )
    assert record.scene_name == "berthoud_pass_co"
    assert record.terrain_rendering_type == "real"
    assert record.coverage_distance_miles == 10.0
    assert record.camera_id == 1
    assert record.camera_position is not None
    assert record.camera_look_dir is not None
    assert record.fog_type == "marched"
    assert record.fog_volume_name == "windy_whipped"
    assert record.exp_fog_density == 0.6


def test_record_masks(ray_lib):
    record = ray_lib.query().where("path = ?", (FRAME_0,)).first()
    assert record.mask_paths == {
        "ray_distance": "2026-06-13_21-40-15/Frame-0_distMask.tif",
        "ray_normalized_distance": (
            "2026-06-13_21-40-15/Frame-0_distNormSmlMask.tif"
        ),
        "ray_validity": "2026-06-13_21-40-15/Frame-0_validMask.png",
    }


def test_auto_fallback_including(ray_lib):
    record = ray_lib.query().where("path = ?", (FRAME_0,)).first()
    assert record.visibility_metric == RAY_INCLUDING_INVALID
    assert record.visibility_value == pytest.approx(7197.180718457964)
    assert record.visibility_meters == record.visibility_value
    assert record.visibility_miles == pytest.approx(7197.180718457964 / 1609.344)
    assert record.simple_value is None
    assert record.ray_excluding_average is None
    assert record.ray_excluding_ray_count == 0


def test_auto_fallback_excluding(ray_lib):
    record = (
        ray_lib.query()
        .where("path = ?", ("2026-06-13_21-45-51/Frame-8.png",))
        .first()
    )
    assert record.visibility_metric == RAY_EXCLUDING_INVALID
    assert record.visibility_value == pytest.approx(23999.276329627402)
    assert record.ray_including_average is None


def test_auto_fallback_simple(ray_lib):
    record = (
        ray_lib.query()
        .where("path = ?", ("2026-06-13_22-01-00/Frame-0.png",))
        .first()
    )
    assert record.visibility_metric == SIMPLE
    assert record.visibility_value == pytest.approx(5000.0)
    assert record.visibility_by_metric == {
        SIMPLE: 5000.0,
        RAY_INCLUDING_INVALID: 20735.01779993905,
        RAY_EXCLUDING_INVALID: None,
    }


def test_simple_only_dataset(simple_lib):
    records = simple_lib.query().order_by("path").records()
    assert [record.visibility_metric for record in records] == [SIMPLE, SIMPLE]
    assert [record.visibility_value for record in records] == pytest.approx(
        [1000.0, 2666.66650390625]
    )


def test_scene_and_camera_filters(ray_lib):
    assert ray_lib.query().scenes(1).count() == 6
    assert ray_lib.query().scene(1).count() == 6
    assert ray_lib.query().scenes(2).count() == 0
    assert ray_lib.query().cameras(1).count() == 6
    assert ray_lib.query().camera(99).count() == 0


def test_scene_name_filter(ray_lib):
    assert ray_lib.query().scene_name("berthoud").count() == 6
    assert ray_lib.query().scene_name("BERTHOUD").count() == 6
    assert ray_lib.query().scene_name("pass").count() == 6
    assert ray_lib.query().scene_name("berthoud", exact=True).count() == 0
    assert ray_lib.query().scene_name("berthoud_pass_co", exact=True).count() == 6
    assert ray_lib.query().scene_name("nope").count() == 0


def test_terrain_filter(ray_lib):
    assert ray_lib.query().terrain("real").count() == 6
    assert ray_lib.query().terrain("REAL").count() == 6
    assert ray_lib.query().terrain("synthetic").count() == 0


def test_fog_filters(ray_lib):
    assert ray_lib.query().fog_type("marched").count() == 6
    assert ray_lib.query().fog_type("MARCHED").count() == 6
    assert ray_lib.query().fog_type("linear").count() == 0
    assert ray_lib.query().fog_volume("clouds").count() == 2
    assert ray_lib.query().fog_volume("CLOUDS").count() == 2
    assert ray_lib.query().fog_volume("windy_whipped").count() == 4
    assert ray_lib.query().exp_fog_density(min=0.6, max=0.6).count() == 6
    assert ray_lib.query().exp_fog_density(min=0.5, max=0.7).count() == 6
    assert ray_lib.query().exp_fog_density(max=0.5).count() == 0


def test_session_filters(ray_lib):
    assert ray_lib.query().sessions("2026-06-13_21-40-15").count() == 2
    assert (
        ray_lib.query()
        .sessions("2026-06-13_21-40-15", "2026-06-14_08-00-00")
        .count()
        == 3
    )
    assert ray_lib.query().sessions("nope").count() == 0


def test_date_range(ray_lib):
    assert ray_lib.query().date_range("2026-06-13").count() == 6
    assert ray_lib.query().date_range("2026-06-14").count() == 1
    assert (
        ray_lib.query().date_range("2026-06-13", "2026-06-13").count() == 5
    )
    assert ray_lib.query().date_range(start="2026-06-14").count() == 1
    assert ray_lib.query().date_range(end="2026-06-13").count() == 5
    assert ray_lib.query().date_range(date(2026, 6, 13)).count() == 6
    assert (
        ray_lib.query().date_range(start="2026-06-13_21:50:00").count() == 2
    )
    assert (
        ray_lib.query()
        .date_range(end=datetime(2026, 6, 13, 21, 45, 51))
        .count()
        == 4
    )
    aware = datetime(2026, 6, 13, 21, 45, 51, tzinfo=timezone.utc)
    assert ray_lib.query().date_range(end=aware).count() == 4
    assert (
        ray_lib.query().date_range(start="2026-06-13 21:45:51").count() == 4
    )


def test_visibility_filters(ray_lib):
    assert ray_lib.query().visibility(max_meters=10000).count() == 2
    assert ray_lib.query().visibility(min_meters=11000).count() == 3
    assert (
        ray_lib.query().visibility(min_meters=10000, max_meters=16000).count()
        == 3
    )
    assert ray_lib.query().visibility(max_meters=1).count() == 0
    assert (
        ray_lib.query().visibility(min_meters=1, max_meters=2).count()
        == 0
    )


def test_visibility_metric_filter(ray_lib):
    assert ray_lib.query().visibility_metric(SIMPLE).count() == 1
    assert ray_lib.query().visibility_metric(RAY_INCLUDING_INVALID).count() == 4
    assert ray_lib.query().visibility_metric(RAY_EXCLUDING_INVALID).count() == 3
    assert (
        ray_lib.query()
        .visibility_metric(RAY_INCLUDING_INVALID, RAY_EXCLUDING_INVALID)
        .count()
        == 6
    )
    assert (
        ray_lib.query()
        .visibility_metric(SIMPLE)
        .paths()
        == ["2026-06-13_22-01-00/Frame-0.png"]
    )


def test_has_visibility_and_masks(ray_lib):
    assert ray_lib.query().has_visibility(True).count() == 6
    assert ray_lib.query().has_visibility(False).count() == 0
    assert ray_lib.query().has_masks(True).count() == 5
    assert ray_lib.query().has_masks(False).count() == 1
    assert (
        ray_lib.query().has_masks(False).paths()
        == ["2026-06-13_21-45-51/Frame-9.png"]
    )


def test_where_escape_hatch(ray_lib):
    assert ray_lib.query().where("width = ?", (1280,)).count() == 6
    assert ray_lib.query().where("height = ?", (720,)).count() == 6
    assert ray_lib.query().where("visibility_value > ?", (20000,)).count() == 1
    assert ray_lib.query().where("scene_name LIKE ?", ("%pass%",)).count() == 6


def test_filters_compose_with_and(ray_lib):
    query = (
        ray_lib.query()
        .scene_name("berthoud")
        .fog_volume("clouds")
        .visibility(min_meters=1000, max_meters=10000)
    )
    assert query.count() == 1
    assert query.paths() == ["2026-06-13_22-01-00/Frame-0.png"]


def test_selections_are_immutable(ray_lib):
    base = ray_lib.query()
    narrowed = base.scene_name("nope")
    assert base.count() == 6
    assert narrowed.count() == 0
    assert base.clauses == ()
    assert len(narrowed.clauses) == 1


def test_order_and_first(ray_lib):
    values = [
        record.visibility_value
        for record in ray_lib.query().order_by("visibility_value").records()
    ]
    assert values == sorted(values)
    assert (
        ray_lib.query().order_by("visibility_value").first().visibility_value
        == pytest.approx(5000.0)
    )
    newest = ray_lib.query().order_by("captured_at", ascending=False).first()
    assert newest.path == "2026-06-14_08-00-00/Frame-0.png"


def test_limit_and_count(ray_lib):
    assert ray_lib.query().limit(2).count() == 6
    assert len(ray_lib.query().limit(2).records()) == 2
    assert ray_lib.query().limit(0).count() == 6
    assert ray_lib.query().limit(0).records() == []
    assert ray_lib.query().count() == 6


def test_paths_and_absolute_paths(ray_lib):
    paths = ray_lib.query().order_by("path").paths()
    assert paths == sorted(paths)
    assert len(paths) == 6
    absolute = ray_lib.query().order_by("path").absolute_paths()
    assert all(path.exists() for path in absolute)
    assert absolute[0] == ray_lib.data_dir / paths[0]


def test_iter_records_streams(ray_lib):
    iterator = ray_lib.query().iter_records()
    first = next(iterator)
    assert first.path in ray_lib.query().paths()
    assert len(list(iterator)) == 5


def test_counts_by(ray_lib):
    assert ray_lib.query().counts_by("session") == {
        "2026-06-13_21-40-15": 2,
        "2026-06-13_21-45-51": 2,
        "2026-06-13_22-01-00": 1,
        "2026-06-14_08-00-00": 1,
    }
    assert ray_lib.query().counts_by("date") == {
        "2026-06-13": 5,
        "2026-06-14": 1,
    }
    assert ray_lib.query().counts_by("scene") == {"berthoud_pass_co": 6}
    assert ray_lib.query().counts_by("terrain") == {"berthoud_pass_co": 6}
    assert ray_lib.query().counts_by("rendering_type") == {"real": 6}
    assert ray_lib.query().counts_by("fog_type") == {"marched": 6}
    assert ray_lib.query().counts_by("fog_volume") == {
        "windy_whipped": 4,
        "clouds": 2,
    }
    assert ray_lib.query().counts_by("metric") == {
        RAY_INCLUDING_INVALID: 3,
        RAY_EXCLUDING_INVALID: 2,
        SIMPLE: 1,
    }
    assert ray_lib.query().counts_by("format") == {"color": 6}


def test_counts_by_respects_filters(ray_lib):
    assert ray_lib.query().fog_volume("clouds").counts_by("session") == {
        "2026-06-13_22-01-00": 1,
        "2026-06-14_08-00-00": 1,
    }


def test_empty_selection_terminals(ray_lib):
    empty = ray_lib.query().sessions("nope")
    assert empty.count() == 0
    assert empty.records() == []
    assert empty.first() is None
    assert empty.paths() == []
    assert empty.counts_by("session") == {}


@pytest.mark.parametrize(
    "call",
    [
        lambda q: q.scenes(),
        lambda q: q.cameras(),
        lambda q: q.scene_name(""),
        lambda q: q.terrain(""),
        lambda q: q.fog_type(),
        lambda q: q.fog_volume(),
        lambda q: q.exp_fog_density(),
        lambda q: q.visibility(),
        lambda q: q.visibility(min_meters=10, max_meters=5),
        lambda q: q.visibility_metric(),
        lambda q: q.visibility_metric("bogus"),
        lambda q: q.sessions(),
        lambda q: q.date_range(),
        lambda q: q.date_range("not-a-date"),
        lambda q: q.where(""),
        lambda q: q.order_by("nope"),
        lambda q: q.limit(-1),
        lambda q: q.counts_by("nope"),
    ],
)
def test_invalid_arguments_raise(ray_lib, call):
    with pytest.raises(ValueError):
        call(ray_lib.query())


def test_order_by_rejects_injection(ray_lib):
    with pytest.raises(ValueError):
        ray_lib.query().order_by("path; DROP TABLE image")
