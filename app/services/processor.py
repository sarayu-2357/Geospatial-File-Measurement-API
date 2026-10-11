"""The orchestrator: ties ingestion, CRS handling, measurement and the DB together.

Flow for one upload:
  1. check the extension (cheap, before touching the DB)
  2. create an UploadedFile row with status PROCESSING
  3. move the upload into permanent storage
  4. read features -> measure each one independently -> save rows
  5. mark COMPLETED, or FAILED with an error message
"""
import json
import logging
import shutil
import tempfile
from pathlib import Path

import shapely
from sqlalchemy.orm import Session

from app import config
from app.errors import GeoAPIError
from app.models import FeatureRecord, FileStatus, UploadedFile
from app.services.crs import crs_label, reproject_to_wgs84, resolve_crs
from app.services.ingestion import RawFeature, load_features, validate_extension
from app.services.measurement import measure_geometry

logger = logging.getLogger(__name__)


def process_upload(db: Session, uploaded_path: Path, original_filename: str) -> UploadedFile:
    """Process one uploaded file and return its saved record.

    On a bad file, the record is saved as FAILED and the original error is
    re-raised with `file_id` attached, so the API can return a proper HTTP error
    AND the client can still look the record up.
    """
    suffix = validate_extension(original_filename)      # raises 415 before any DB row exists

    record = UploadedFile(filename=Path(original_filename).name, status=FileStatus.PROCESSING)
    db.add(record)
    db.commit()
    logger.info("Created file record %s for '%s'", record.id, record.filename)

    try:
        stored_path = _store_original(uploaded_path, record.id, suffix)
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as workdir:
            raw_features = load_features(stored_path, original_filename, Path(workdir))
            rows, file_crs = _measure_all(raw_features)

        record.features = rows
        record.crs = file_crs
        record.feature_count = len(rows)
        record.status = FileStatus.COMPLETED
        db.commit()
        logger.info("File %s completed: %d features", record.id, len(rows))
        return record

    except GeoAPIError as exc:
        logger.warning("File %s failed: %s", record.id, exc.message)
        _mark_failed(db, record, exc.message)
        exc.file_id = record.id
        raise
    except Exception:
        logger.exception("File %s failed with an unexpected error", record.id)
        _mark_failed(db, record, "Unexpected internal error while processing the file.")
        raise


def _store_original(uploaded_path: Path, file_id: str, suffix: str) -> Path:
    """Move the upload to uploads/<file_id>/original.<ext>.

    We never use the client's filename on disk (it could contain '../' tricks).
    """
    dest_dir = config.UPLOAD_DIR / file_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"original{suffix}"
    shutil.move(str(uploaded_path), str(dest))
    return dest


def _mark_failed(db: Session, record: UploadedFile, message: str) -> None:
    db.rollback()   # discard any half-written rows first
    record.status = FileStatus.FAILED
    record.error_message = message
    db.commit()


def _measure_all(raw_features: list[RawFeature]) -> tuple[list[FeatureRecord], str]:
    """Measure every feature independently. Returns (rows, file-level CRS label)."""
    crs_cache: dict = {}            # crs text -> (CRS object, label); avoids re-parsing per feature
    transformer_cache: dict = {}    # epsg -> Transformer; lives for this one request only
    rows: list[FeatureRecord] = []
    labels: set[str] = set()

    for feature in raw_features:
        if feature.crs not in crs_cache:
            crs = resolve_crs(feature.crs)
            crs_cache[feature.crs] = (crs, crs_label(crs))
        crs, label = crs_cache[feature.crs]
        labels.add(label)
        rows.append(_build_row(feature, crs, label, transformer_cache))

    file_crs = next(iter(labels)) if len(labels) == 1 else "MIXED: " + ", ".join(sorted(labels))
    return rows, file_crs


def _build_row(feature: RawFeature, crs, label: str, transformer_cache: dict) -> FeatureRecord:
    """Measure one feature. A failure here only affects THIS feature."""
    try:
        wgs84 = reproject_to_wgs84(feature.geometry, crs) if feature.geometry is not None else None
        measurement = measure_geometry(wgs84, transformer_cache)
    except Exception as exc:
        logger.warning("Feature %s could not be measured: %s", feature.index, exc)
        measurement = {"status": "error", "reason": f"Reprojection failed: {exc}"}

    return FeatureRecord(
        feature_index=feature.index,
        layer=feature.layer,
        geometry_type=feature.geometry.geom_type if feature.geometry is not None else None,
        geometry=_to_geojson(feature.geometry),
        crs=label,
        properties=feature.properties,
        measurement=measurement,
    )


def _to_geojson(geom) -> dict | None:
    return json.loads(shapely.to_geojson(geom)) if geom is not None else None