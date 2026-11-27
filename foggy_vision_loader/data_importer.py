from foggy_vision_loader.db import (
    DatabaseWriter,
    DatabaseCleanup,
    ImageImporter,
    SceneEntity,
    CoordinateEntity,
    Database,
)
from foggy_vision_loader.db.entities import (
    ImageEntity,
    ViewEntity,
    ViewImageEntity,
    VisibilityDistanceEntity,
)
from foggy_vision_loader.common import Latitude, Longitude
from tqdm import tqdm
from dataclasses import dataclass
from typing import Any
from itertools import repeat
import os
import shutil
import queue
import threading
from PIL import Image
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

_DONE = object()
_ABORT = object()


@dataclass
class InputImage:
    image_path: Path
    image_data_file_path: Path


def collect_input_images(root_dir: str) -> list:
    """
    Recurse through a directory tree, collecting all .json files and their
    partner images into InputImage dataclasses. Image paths are resolved
    relative to each JSON file using the file_name and ray_masks fields.
    """
    root = Path(root_dir)
    if not root.exists():
        raise FileNotFoundError(f"Directory not found: {root}")

    input_images = []

    for json_path in sorted(root.rglob("*.json")):
        reader = ImageImporter(json_path)
        data = reader._data

        if "image_files" in data:
            color_rel = data["image_files"].get("file_name", "")
        else:
            color_rel = data.get("file_name", "")

        if not color_rel:
            raise ValueError(f"JSON file missing file_name: {json_path}")

        color_path = (json_path.parent / color_rel).resolve()
        if not color_path.exists():
            raise ValueError(f"Missing partner image for: {json_path}")

        input_images.append(
            InputImage(image_path=color_path, image_data_file_path=json_path)
        )

    return input_images


def _images_dir(db_dir: Path) -> Path:
    return Path(db_dir) / "images"


def _copy_into_db(source: Path, db_dir: Path) -> Path:
    """Copy a file into the db images dir under a subdirectory named after
    the source's parent, keeping the original file name. Files already in
    place (e.g. during a rebuild) are left untouched.
    """
    dest = _images_dir(db_dir) / source.parent.name / source.name
    if source.resolve() == dest.resolve():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)
    return dest


def _relative_name(path: Path, db_dir: Path) -> str:
    """Path relative to the db images dir; this is what the image table
    stores as fileName, since bare file names are not unique across dates.
    """
    return path.resolve().relative_to(_images_dir(db_dir).resolve()).as_posix()


def copy_ray_masks(json_path: Path, db_dir: Path) -> dict[str, str]:
    """Copy the ray mask files referenced by a JSON file into the db images
    dir, returning mask type to path relative to the images directory.
    """
    reader = ImageImporter(json_path)
    data = reader._data

    if "image_files" in data:
        ray_masks = data["image_files"].get("distance_mask_images", {})
    else:
        ray_masks = data.get("ray_masks", {})

    result: dict[str, str] = {}

    for key in (
        "ray_distance_name",
        "ray_normalized_distance_name",
        "ray_validity_name",
    ):
        rel_path = ray_masks.get(key, "")
        if not rel_path:
            result[key] = ""
            continue

        source = (json_path.parent / rel_path).resolve()
        if not source.exists():
            result[key] = ""
            continue

        dest = _copy_into_db(source, db_dir)
        result[key] = _relative_name(dest, db_dir)

    return result


def parse_image_data_file(filepath: Path) -> dict[str, Any]:
    reader: ImageImporter = ImageImporter(filepath)
    scene_data = reader.read_scene()

    return {
        "scene_name": scene_data.name,
        "scene_rendering_type": scene_data.rendering_type,
        "scene_center": CoordinateEntity(
            lat=Latitude(str(scene_data.center.y)),
            lon=Longitude(str(scene_data.center.x)),
        ),
        "scene_vis_range": scene_data.vis_range,
        "terrain_shape_center": scene_data.center.to_json(),
        "camera": reader.read_camera(),
        "fog": reader.read_fog(),
        "fog_type": reader.read_fog_type(),
        "skybox": reader.read_skybox(),
        "light": reader.read_light(),
        "light_type": reader.read_light_type(),
        "environment": reader.read_environment(),
        # environment.light_ids will be filled in by write_full_scene once the light id is known
    }


def Get_Image_Metadata(img_path):
    with Image.open(img_path) as img:
        return img.size


def process_image_data(
    image: InputImage,
    db_dir: Path,
) -> dict[str, Any]:
    imported_image_path: Path = _copy_into_db(image.image_path, db_dir)
    parsed = parse_image_data_file(image.image_data_file_path)
    masks = copy_ray_masks(image.image_data_file_path, db_dir)
    _copy_into_db(image.image_data_file_path, db_dir)
    width, height = Get_Image_Metadata(imported_image_path)

    color_image = ImageEntity(
        file_name=_relative_name(imported_image_path, db_dir),
        file_type="color",
        width=width,
        height=height,
    )

    images = [color_image]
    images_by_role: dict[str, ImageEntity] = {}

    for role, key in (
        ("ray_distance", "ray_distance_name"),
        ("ray_normalized_distance", "ray_normalized_distance_name"),
        ("ray_validity", "ray_validity_name"),
    ):
        mask_name = masks.get(key, "")
        if mask_name:
            mask_path = _images_dir(db_dir) / mask_name
            mask_width, mask_height = Get_Image_Metadata(mask_path)
            mask_entity = ImageEntity(
                file_name=mask_name,
                file_type=role,
                width=mask_width,
                height=mask_height,
            )
            images.append(mask_entity)
            images_by_role[role] = mask_entity

    view = ViewEntity(
        color_image_id=0,
        camera_id=0,
        scene_id=0,
        environment_id=0,
    )

    view_images: list[ViewImageEntity] = []
    for role, mask_entity in images_by_role.items():
        view_images.append(ViewImageEntity(view_id=0, image_id=0, role=role))

    json_reader: ImageImporter = ImageImporter(image.image_data_file_path)
    visibility_distances: list[VisibilityDistanceEntity] = (
        json_reader.read_visibility_distances(view_id=0)
    )

    parsed["images"] = images
    parsed["views"] = [view]
    parsed["view_images"] = view_images
    parsed["visibility_distances"] = visibility_distances

    return parsed


def writer_thread(
    d: Database,
    write_queue: queue.Queue,
    writer_error: list[BaseException],
    batch_size: int = 50,
) -> None:
    """Single dedicated thread — owns all DB access.

    Failures are recorded in ``writer_error`` so ``process_files`` can raise
    them on the caller's thread instead of silently returning a partial
    database. Receiving ``_ABORT`` (sent when a worker failed mid-import)
    raises inside the ``with d:`` block so the connection closes without
    committing and the partial import rolls back.
    """
    writer = DatabaseWriter(d)
    batch = []

    # One connection for the writer's lifetime avoids open/close per row.
    try:
        with d:
            while True:
                item = write_queue.get()
                if item is _ABORT:
                    raise RuntimeError(
                        "Import aborted after a processing failure; "
                        "rolling back the partial import"
                    )
                if item is _DONE:
                    if batch:
                        _flush(writer, batch)
                    break

                batch.append(item)
                if len(batch) >= batch_size:
                    _flush(writer, batch)
                    batch.clear()

                write_queue.task_done()
    except BaseException as exc:  # re-raised on the caller's thread
        writer_error.append(exc)
        # Unblock a producer that may be waiting on a full queue.
        while True:
            try:
                queued = write_queue.get_nowait()
            except queue.Empty:
                break
            if queued is not _DONE and queued is not _ABORT:
                write_queue.task_done()


def _put(
    write_queue: queue.Queue,
    item: object,
    writer: threading.Thread,
    writer_error: list[BaseException],
    timeout: float = 0.1,
) -> bool:
    """Enqueue without blocking forever if the writer thread has died."""
    while writer.is_alive() and not writer_error:
        try:
            write_queue.put(item, timeout=timeout)
            return True
        except queue.Full:
            continue
    return False


def process_files(
    importFilePaths: list[InputImage],
    db_dir: Path,
    max_workers: int = 1,
):
    write_queue: queue.Queue = queue.Queue(maxsize=500)
    writer_error: list[BaseException] = []
    total = len(importFilePaths)
    if total == 0:
        raise ValueError("No frame JSON files to import")

    db = Database(db_dir)
    db.init_tables()

    writer = threading.Thread(
        target=writer_thread,
        args=(db, write_queue, writer_error),
        daemon=True,
    )
    writer.start()

    worker_failed = False
    try:
        with tqdm(total=total, desc="Processing files", unit="file") as progress_bar:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                try:
                    for result in executor.map(
                        process_image_data, importFilePaths, repeat(db_dir)
                    ):
                        if writer_error:
                            break
                        if not _put(write_queue, result, writer, writer_error):
                            break
                        progress_bar.update(1)
                except BaseException:
                    # A worker failed (bad image, unreadable JSON, ...).
                    # Mark it so the writer rolls back instead of committing
                    # the frames that had already been queued.
                    worker_failed = True
                    raise
    finally:
        # Always stop the writer, including when a worker raised.
        # _DONE commits the batch; _ABORT rolls it back.
        _put(
            write_queue,
            _ABORT if worker_failed else _DONE,
            writer,
            writer_error,
        )
        writer.join()

    if writer_error:
        raise RuntimeError("Database write failed during import") from writer_error[0]


def _flush(writer: DatabaseWriter, batch: list[dict]) -> None:
    for item in batch:
        writer.write_full_scene(**item)


def cleanup_db(db_dir: Path) -> object:
    """Remove orphaned image *files* from disk; no database rows are modified.

    Prints a one-line summary and returns the DatabaseCleanup report. Raises
    ``RuntimeError`` if any file could not be deleted.
    """
    db = Database(db_dir)
    report = DatabaseCleanup(db).sweep_orphaned_disk_files()
    print(report)
    if report.errors:
        failed = ", ".join(report.errors)
        raise RuntimeError(
            f"Cleanup failed to delete {len(report.errors)} file(s): {failed}"
        )
    return report


def main(
    db_dir: Path,
    import_dir: Path,
):
    if not os.path.exists(import_dir):
        raise Exception("Import image directory does not exist")

    inputs = collect_input_images(import_dir)
    if not inputs:
        raise ValueError(f"No frame JSON files found in {import_dir}")

    db = Database(db_dir)
    image_output_dir: Path = db.import_dir
    if not os.path.exists(image_output_dir):
        os.makedirs(image_output_dir)

    process_files(inputs, db_dir)


def rebuild_db(db_dir: Path):
    """Wipe database.sqlite3 and rebuild it by parsing the db images dir as
    an import source. Files already in place are not copied again.
    """
    db = Database(db_dir)
    images_dir: Path = Path(db.import_dir)
    if not os.path.exists(images_dir):
        raise FileNotFoundError(
            f"Cannot rebuild: images directory does not exist: {images_dir}"
        )

    # Parse and validate the tree before replacing the current database.
    inputs = collect_input_images(images_dir)
    if not inputs:
        raise ValueError(
            f"Cannot rebuild: no frame JSON files found in {images_dir}"
        )

    db_path = Path(db.db_path)
    backup_path = db_path.with_name(db_path.name + ".rebuild-backup")
    had_database = db_path.exists()

    if had_database:
        if backup_path.exists():
            os.remove(backup_path)
        os.replace(db_path, backup_path)

    try:
        process_files(inputs, db_dir)
    except BaseException:
        # Restore the previous database so a failed rebuild is not destructive.
        try:
            if db_path.exists():
                os.remove(db_path)
            if had_database and backup_path.exists():
                os.replace(backup_path, db_path)
        except OSError:
            # Keep the original failure; the backup remains on disk.
            pass
        raise
    else:
        if backup_path.exists():
            os.remove(backup_path)

    cleanup_db(db_dir)