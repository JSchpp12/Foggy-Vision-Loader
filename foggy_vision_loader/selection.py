"""Composable, immutable queries over a FoggyVision database."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, Any, Iterator, Optional

from .records import (
    DISTANCE_METRICS,
    RAY_EXCLUDING_INVALID,
    RAY_INCLUDING_INVALID,
    SIMPLE,
    ImageRecord,
)

if TYPE_CHECKING:  # pragma: no cover - avoids an import cycle at runtime
    from .library import FoggyVisionLibrary


#: GLOB matching a session-folder prefix: YYYY-MM-DD_HH-MM-SS/
_SESSION_GLOB = (
    "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]_"
    "[0-9][0-9]-[0-9][0-9]-[0-9][0-9]/*"
)

_INNER_SQL = f"""
SELECT
    i.fileName                                        AS path,
    i.fileType                                        AS format,
    i.width                                           AS width,
    i.height                                          AS height,
    CASE WHEN i.fileName GLOB '{_SESSION_GLOB}'
         THEN substr(i.fileName, 1, 19) END           AS session,
    v.sceneID                                         AS scene_id,
    s.name                                            AS scene_name,
    s.terrainRenderingType                            AS terrain_rendering_type,
    s.coverageDistanceMiles                           AS coverage_distance_miles,
    v.cameraID                                        AS camera_id,
    c.virtualPosition                                 AS camera_position,
    c.lookDir                                         AS camera_look_dir,
    v.environmentID                                   AS environment_id,
    f.id                                              AS fog_id,
    ft.name                                           AS fog_type,
    f.volumeName                                      AS fog_volume_name,
    f.expFogDensity                                   AS exp_fog_density,
    f.marchedDensityMultiplier                        AS marched_density_multiplier,
    vs.value                                          AS simple_value,
    ve.average                                        AS ray_excluding_average,
    ve.median                                         AS ray_excluding_median,
    ve.minimum                                        AS ray_excluding_minimum,
    ve.rayCount                                       AS ray_excluding_ray_count,
    vi.average                                        AS ray_including_average,
    vi.median                                         AS ray_including_median,
    vi.minimum                                        AS ray_including_minimum,
    vi.rayCount                                       AS ray_including_ray_count,
    md.fileName                                       AS ray_distance_path,
    mn.fileName                                       AS ray_normalized_distance_path,
    mv.fileName                                       AS ray_validity_path
FROM image AS i
JOIN (
    SELECT colorImageID AS image_id, MIN(id) AS view_id
    FROM view
    GROUP BY colorImageID
) AS vp ON vp.image_id = i.id
JOIN view AS v           ON v.id = vp.view_id
JOIN scene AS s          ON s.id = v.sceneID
JOIN camera AS c         ON c.id = v.cameraID
JOIN environment AS e    ON e.id = v.environmentID
JOIN fog AS f            ON f.id = e.fogID
JOIN fog_type AS ft      ON ft.id = f.typeID
LEFT JOIN visibility_distance AS vs
       ON vs.viewID = v.id AND vs.distanceType = '{SIMPLE}'
LEFT JOIN visibility_distance AS vi
       ON vi.viewID = v.id AND vi.distanceType = '{RAY_INCLUDING_INVALID}'
LEFT JOIN visibility_distance AS ve
       ON ve.viewID = v.id AND ve.distanceType = '{RAY_EXCLUDING_INVALID}'
LEFT JOIN view_image AS vd
       ON vd.viewID = v.id AND vd.role = 'ray_distance'
LEFT JOIN image AS md    ON md.id = vd.imageID
LEFT JOIN view_image AS vn
       ON vn.viewID = v.id AND vn.role = 'ray_normalized_distance'
LEFT JOIN image AS mn    ON mn.id = vn.imageID
LEFT JOIN view_image AS vv
       ON vv.viewID = v.id AND vv.role = 'ray_validity'
LEFT JOIN image AS mv    ON mv.id = vv.imageID
WHERE i.fileType = 'color'
"""

#: One row per color image, including the resolved visibility fallback.
CATALOG_SQL = f"""
SELECT
    base.*,
    COALESCE(
        base.simple_value,
        base.ray_including_average,
        base.ray_excluding_average
    ) AS visibility_value,
    CASE
        WHEN base.simple_value IS NOT NULL THEN '{SIMPLE}'
        WHEN base.ray_including_average IS NOT NULL THEN '{RAY_INCLUDING_INVALID}'
        WHEN base.ray_excluding_average IS NOT NULL THEN '{RAY_EXCLUDING_INVALID}'
    END AS visibility_metric
FROM ({_INNER_SQL}) AS base
"""

_ORDER_COLUMNS = {
    "path": "path",
    "format": "format",
    "width": "width",
    "height": "height",
    "session": "session",
    "captured_at": "session",
    "date": "substr(session, 1, 10)",
    "scene_id": "scene_id",
    "scene_name": "scene_name",
    "scene": "scene_name",
    "terrain": "scene_name",
    "terrain_rendering_type": "terrain_rendering_type",
    "coverage_distance_miles": "coverage_distance_miles",
    "camera_id": "camera_id",
    "camera": "camera_id",
    "fog_id": "fog_id",
    "fog_type": "fog_type",
    "fog_volume_name": "fog_volume_name",
    "fog_volume": "fog_volume_name",
    "exp_fog_density": "exp_fog_density",
    "marched_density_multiplier": "marched_density_multiplier",
    "visibility_value": "visibility_value",
    "visibility": "visibility_value",
    "visibility_metric": "visibility_metric",
    "metric": "visibility_metric",
    "simple_value": "simple_value",
    "ray_excluding_average": "ray_excluding_average",
    "ray_including_average": "ray_including_average",
}

_COUNT_COLUMNS = {
    "scene": "scene_name",
    "scene_name": "scene_name",
    "terrain": "scene_name",
    "terrain_rendering_type": "terrain_rendering_type",
    "rendering_type": "terrain_rendering_type",
    "camera": "camera_id",
    "camera_id": "camera_id",
    "fog_type": "fog_type",
    "fog_volume": "fog_volume_name",
    "fog_volume_name": "fog_volume_name",
    "session": "session",
    "date": "substr(session, 1, 10)",
    "metric": "visibility_metric",
    "visibility_metric": "visibility_metric",
    "format": "format",
}

_METRIC_COLUMNS = {
    SIMPLE: "simple_value",
    RAY_INCLUDING_INVALID: "ray_including_average",
    RAY_EXCLUDING_INVALID: "ray_excluding_average",
}

_MASK_COLUMNS = (
    "ray_distance_path",
    "ray_normalized_distance_path",
    "ray_validity_path",
)


@dataclass(frozen=True, slots=True)
class _Clause:
    sql: str
    params: tuple = ()


@dataclass(frozen=True)
class Selection:
    """A composable query over the FoggyVision image catalog.

    Every filter returns a new :class:`Selection`; selections are immutable and
    can be shared.  Only terminal methods execute SQL.
    """

    library: Any
    clauses: tuple[_Clause, ...] = ()
    order: Optional[tuple[str, bool]] = None
    max_rows: Optional[int] = None

    # ---------------------------------------------------------------- filters

    def _filter(self, sql: str, params: tuple = ()) -> "Selection":
        return replace(self, clauses=self.clauses + (_Clause(sql, tuple(params)),))

    def scenes(self, *scene_ids: int) -> "Selection":
        if not scene_ids:
            raise ValueError("scenes() requires at least one scene id")
        ids = [int(value) for value in scene_ids]
        return self._filter(
            f"scene_id IN ({', '.join('?' for _ in ids)})", tuple(ids)
        )

    def scene(self, scene_id: int) -> "Selection":
        return self.scenes(scene_id)

    def cameras(self, *camera_ids: int) -> "Selection":
        if not camera_ids:
            raise ValueError("cameras() requires at least one camera id")
        ids = [int(value) for value in camera_ids]
        return self._filter(
            f"camera_id IN ({', '.join('?' for _ in ids)})", tuple(ids)
        )

    def camera(self, camera_id: int) -> "Selection":
        return self.cameras(camera_id)

    def terrain(self, rendering_type: str) -> "Selection":
        if not rendering_type:
            raise ValueError("terrain() requires a rendering type")
        return self._filter(
            "lower(terrain_rendering_type) = lower(?)", (rendering_type,)
        )

    def scene_name(self, name: str, *, exact: bool = False) -> "Selection":
        """Filter by terrain/scene name (case-insensitive substring by default)."""
        if not name:
            raise ValueError("scene_name() requires a name")
        if exact:
            return self._filter("lower(scene_name) = lower(?)", (name,))
        return self._filter("lower(scene_name) LIKE lower(?)", (f"%{name}%",))

    def fog_type(self, *names: str) -> "Selection":
        if not names:
            raise ValueError("fog_type() requires at least one name")
        lowered = [name.lower() for name in names]
        return self._filter(
            f"lower(fog_type) IN ({', '.join('?' for _ in lowered)})", tuple(lowered)
        )

    def fog_volume(self, *names: str) -> "Selection":
        if not names:
            raise ValueError("fog_volume() requires at least one name")
        lowered = [name.lower() for name in names]
        return self._filter(
            f"lower(fog_volume_name) IN ({', '.join('?' for _ in lowered)})",
            tuple(lowered),
        )

    def exp_fog_density(
        self, *, min: Optional[float] = None, max: Optional[float] = None
    ) -> "Selection":
        return self._range("exp_fog_density", min, max, "exp_fog_density")

    def visibility(
        self,
        *,
        min_meters: Optional[float] = None,
        max_meters: Optional[float] = None,
    ) -> "Selection":
        return self._range("visibility_value", min_meters, max_meters, "visibility")

    def visibility_metric(self, *metrics: str) -> "Selection":
        if not metrics:
            raise ValueError("visibility_metric() requires at least one metric")
        invalid = [metric for metric in metrics if metric not in _METRIC_COLUMNS]
        if invalid:
            raise ValueError(
                f"unknown visibility metric(s): {invalid}; "
                f"expected one of {list(DISTANCE_METRICS)}"
            )
        clause = " OR ".join(
            f"{_METRIC_COLUMNS[metric]} IS NOT NULL" for metric in metrics
        )
        return self._filter(f"({clause})")

    def has_visibility(self, present: bool = True) -> "Selection":
        return self._filter(
            "visibility_value IS NOT NULL"
            if present
            else "visibility_value IS NULL"
        )

    def sessions(self, *names: str) -> "Selection":
        if not names:
            raise ValueError("sessions() requires at least one session name")
        return self._filter(
            f"session IN ({', '.join('?' for _ in names)})", tuple(names)
        )

    def date_range(
        self,
        start: "date | datetime | str | None" = None,
        end: "date | datetime | str | None" = None,
    ) -> "Selection":
        if start is None and end is None:
            raise ValueError("date_range() requires start and/or end")
        selection: Selection = self
        if start is not None:
            selection = selection._filter(
                "session >= ?", (_session_bound(start, upper=False),)
            )
        if end is not None:
            selection = selection._filter(
                "session <= ?", (_session_bound(end, upper=True),)
            )
        return selection

    def has_masks(self, present: bool = True) -> "Selection":
        any_mask = " OR ".join(f"{column} IS NOT NULL" for column in _MASK_COLUMNS)
        if present:
            return self._filter(f"({any_mask})")
        return self._filter(f"NOT ({any_mask})")

    def where(self, sql: str, params: tuple = ()) -> "Selection":
        """Raw predicate over the normalized catalog columns."""
        if not sql or not sql.strip():
            raise ValueError("where() requires a SQL predicate")
        return self._filter(f"({sql})", params)

    def order_by(self, column: str, ascending: bool = True) -> "Selection":
        expression = _ORDER_COLUMNS.get(column)
        if expression is None:
            raise ValueError(
                f"cannot order by {column!r}; expected one of "
                f"{sorted(_ORDER_COLUMNS)}"
            )
        return replace(self, order=(expression, bool(ascending)))

    def limit(self, n: int) -> "Selection":
        if int(n) < 0:
            raise ValueError("limit() requires a non-negative count")
        return replace(self, max_rows=int(n))

    def _range(
        self,
        column: str,
        minimum: Optional[float],
        maximum: Optional[float],
        label: str,
    ) -> "Selection":
        if minimum is None and maximum is None:
            raise ValueError(f"{label}() requires a minimum and/or maximum")
        if minimum is not None and maximum is not None and float(minimum) > float(
            maximum
        ):
            raise ValueError(f"{label}() minimum must not exceed maximum")
        selection: Selection = self
        if minimum is not None:
            selection = selection._filter(f"{column} >= ?", (float(minimum),))
        if maximum is not None:
            selection = selection._filter(f"{column} <= ?", (float(maximum),))
        return selection

    # -------------------------------------------------------------- terminals

    def _where_sql(self) -> tuple[str, tuple]:
        if not self.clauses:
            return "", ()
        sql = " AND ".join(f"({clause.sql})" for clause in self.clauses)
        params: tuple = ()
        for clause in self.clauses:
            params += clause.params
        return sql, params

    def _select_sql(self, columns: str) -> tuple[str, tuple]:
        where, params = self._where_sql()
        sql = f"SELECT {columns} FROM ({CATALOG_SQL}) AS img"
        if where:
            sql += f" WHERE {where}"
        if self.order is not None:
            expression, ascending = self.order
            sql += f" ORDER BY {expression} {'ASC' if ascending else 'DESC'}"
            if expression != "path":
                sql += ", path ASC"
        if self.max_rows is not None:
            sql += " LIMIT ?"
            params += (self.max_rows,)
        return sql, params

    def count(self) -> int:
        where, params = self._where_sql()
        sql = f"SELECT COUNT(*) FROM ({CATALOG_SQL}) AS img"
        if where:
            sql += f" WHERE {where}"
        return int(self.library.conn.execute(sql, params).fetchone()[0])

    def iter_records(self) -> Iterator[ImageRecord]:
        sql, params = self._select_sql("*")
        for row in self.library.conn.execute(sql, params):
            yield _row_to_record(row)

    def records(self) -> list[ImageRecord]:
        return list(self.iter_records())

    def paths(self) -> list[str]:
        sql, params = self._select_sql("path")
        return [row[0] for row in self.library.conn.execute(sql, params)]

    def absolute_paths(self) -> list:
        return [self.library.data_dir / path for path in self.paths()]

    def first(self) -> Optional[ImageRecord]:
        sql, params = replace(self, max_rows=1)._select_sql("*")
        row = self.library.conn.execute(sql, params).fetchone()
        return None if row is None else _row_to_record(row)

    def counts_by(self, field: str) -> dict:
        expression = _COUNT_COLUMNS.get(field)
        if expression is None:
            raise ValueError(
                f"cannot count by {field!r}; expected one of "
                f"{sorted(_COUNT_COLUMNS)}"
            )
        where, params = self._where_sql()
        sql = (
            f"SELECT {expression} AS key, COUNT(*) AS n "
            f"FROM ({CATALOG_SQL}) AS img"
        )
        if where:
            sql += f" WHERE {where}"
        sql += " GROUP BY key ORDER BY n DESC, key"
        return {row["key"]: row["n"] for row in self.library.conn.execute(sql, params)}


def _row_to_record(row: Any) -> ImageRecord:
    return ImageRecord(
        path=row["path"],
        format=row["format"],
        width=row["width"],
        height=row["height"],
        session=row["session"],
        captured_at=_parse_session(row["session"]),
        scene_id=row["scene_id"],
        scene_name=row["scene_name"],
        terrain_rendering_type=row["terrain_rendering_type"],
        coverage_distance_miles=row["coverage_distance_miles"],
        camera_id=row["camera_id"],
        camera_position=row["camera_position"],
        camera_look_dir=row["camera_look_dir"],
        fog_id=row["fog_id"],
        fog_type=row["fog_type"],
        fog_volume_name=row["fog_volume_name"],
        exp_fog_density=row["exp_fog_density"],
        marched_density_multiplier=row["marched_density_multiplier"],
        simple_value=row["simple_value"],
        ray_excluding_average=row["ray_excluding_average"],
        ray_excluding_median=row["ray_excluding_median"],
        ray_excluding_minimum=row["ray_excluding_minimum"],
        ray_excluding_ray_count=row["ray_excluding_ray_count"],
        ray_including_average=row["ray_including_average"],
        ray_including_median=row["ray_including_median"],
        ray_including_minimum=row["ray_including_minimum"],
        ray_including_ray_count=row["ray_including_ray_count"],
        ray_distance_path=row["ray_distance_path"],
        ray_normalized_distance_path=row["ray_normalized_distance_path"],
        ray_validity_path=row["ray_validity_path"],
        visibility_value=row["visibility_value"],
        visibility_metric=row["visibility_metric"],
    )


def _parse_session(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d_%H-%M-%S")
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc)


_STRING_FORMATS = (
    "%Y-%m-%d_%H-%M-%S",
    "%Y-%m-%d_%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H-%M-%S",
)


def _session_bound(value: "date | datetime | str", *, upper: bool) -> str:
    if isinstance(value, datetime):
        moment = value
        if moment.tzinfo is not None:
            moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
        return moment.strftime("%Y-%m-%d_%H-%M-%S")
    if isinstance(value, date):
        suffix = "23-59-59" if upper else "00-00-00"
        return f"{value.isoformat()}_{suffix}"
    if isinstance(value, str):
        text = value.strip()
        if len(text) == 10:
            try:
                parsed_date = date.fromisoformat(text)
            except ValueError as exc:
                raise ValueError(f"invalid date bound: {value!r}") from exc
            suffix = "23-59-59" if upper else "00-00-00"
            return f"{parsed_date.isoformat()}_{suffix}"
        for pattern in _STRING_FORMATS:
            try:
                return datetime.strptime(text, pattern).strftime("%Y-%m-%d_%H-%M-%S")
            except ValueError:
                continue
        raise ValueError(f"invalid date bound: {value!r}")
    raise TypeError(f"unsupported date bound type: {type(value).__name__}")
