"""Data model returned by the FoggyVision query API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

#: Conversion factor used by ``ImageRecord.visibility_miles``.
METERS_PER_MILE = 1609.344

#: ``visibility_distance.distanceType`` values stored by the importer.
SIMPLE = "simple"
RAY_EXCLUDING_INVALID = "ray_excluding_invalid"
RAY_INCLUDING_INVALID = "ray_including_invalid"

DISTANCE_METRICS = (SIMPLE, RAY_EXCLUDING_INVALID, RAY_INCLUDING_INVALID)


@dataclass(frozen=True, slots=True)
class ImageRecord:
    """One color image plus the metadata stored for its view.

    ``path`` is POSIX-style and relative to ``FoggyVisionLibrary.data_dir``
    (the database's ``images`` directory).  No pixel data is loaded.

    Visibility values come from ``visibility_distance``.  Only the ``simple``
    metric has a ``value``; the two ray metrics report ``average``/``median``/
    ``minimum``/``ray_count``.  ``visibility_value`` is the resolved
    auto-fallback value (``simple`` -> ``ray_including_invalid`` ->
    ``ray_excluding_invalid``) and ``visibility_metric`` names the metric that
    supplied it.
    """

    path: str
    format: str
    width: Optional[int]
    height: Optional[int]
    session: Optional[str]
    captured_at: Optional[datetime]

    scene_id: Optional[int] = None
    scene_name: Optional[str] = None
    terrain_rendering_type: Optional[str] = None
    coverage_distance_miles: Optional[float] = None

    camera_id: Optional[int] = None
    camera_position: Optional[str] = None
    camera_look_dir: Optional[str] = None

    fog_id: Optional[int] = None
    fog_type: Optional[str] = None
    fog_volume_name: Optional[str] = None
    exp_fog_density: Optional[float] = None
    marched_density_multiplier: Optional[float] = None

    simple_value: Optional[float] = None
    ray_excluding_average: Optional[float] = None
    ray_excluding_median: Optional[float] = None
    ray_excluding_minimum: Optional[float] = None
    ray_excluding_ray_count: Optional[int] = None
    ray_including_average: Optional[float] = None
    ray_including_median: Optional[float] = None
    ray_including_minimum: Optional[float] = None
    ray_including_ray_count: Optional[int] = None

    ray_distance_path: Optional[str] = None
    ray_normalized_distance_path: Optional[str] = None
    ray_validity_path: Optional[str] = None

    visibility_value: Optional[float] = None
    visibility_metric: Optional[str] = None

    @property
    def visibility_meters(self) -> Optional[float]:
        """Resolved visibility in the renderer's world units (treated as meters)."""
        return self.visibility_value

    @property
    def visibility_miles(self) -> Optional[float]:
        """Resolved visibility converted from meters to statute miles."""
        if self.visibility_value is None:
            return None
        return self.visibility_value / METERS_PER_MILE

    @property
    def visibility_by_metric(self) -> dict[str, Optional[float]]:
        """Resolved numeric value for each metric, ``None`` when unavailable."""
        return {
            SIMPLE: self.simple_value,
            RAY_INCLUDING_INVALID: self.ray_including_average,
            RAY_EXCLUDING_INVALID: self.ray_excluding_average,
        }

    @property
    def mask_paths(self) -> dict[str, str]:
        """Mask role -> POSIX path relative to the images directory."""
        masks = {
            "ray_distance": self.ray_distance_path,
            "ray_normalized_distance": self.ray_normalized_distance_path,
            "ray_validity": self.ray_validity_path,
        }
        return {role: path for role, path in masks.items() if path is not None}
