"""The three endpoints. Kept thin: validate, call a service, shape the response."""
import logging
import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.orm import Session

from app import config
from app.db import get_db
from app.errors import ConflictError, FileTooLargeError, InvalidFileError, NotFoundError
from app.models import FileStatus, UploadedFile
from app.schemas import FeatureOut, FileOut, MeasurementsOut
from app.services.ingestion import validate_extension
from app.services.processor import process_upload

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/files", tags=["files"])

CHUNK_SIZE = 1024 * 1024   # read uploads 1 MB at a time


@router.post("/", response_model=FileOut, status_code=201)
def upload_file(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Upload a .kml or a .zip containing a shapefile, process it, return its record.

    Declared with plain `def` (not `async def`) on purpose: processing is CPU-heavy
    and blocking, so FastAPI runs it in a worker thread instead of freezing the
    event loop.
    """
    suffix = validate_extension(file.filename or "")
    tmp_path = _save_upload_to_temp(file, suffix)
    try:
        return process_upload(db, tmp_path, file.filename)
    finally:
        tmp_path.unlink(missing_ok=True)   # no-op if the processor already moved it


@router.get("/{file_id}/", response_model=FileOut)
def get_file(file_id: str, db: Session = Depends(get_db)):
    return _get_file_or_404(db, file_id)


@router.get("/{file_id}/measurements/", response_model=MeasurementsOut)
def get_measurements(
    file_id: str,
    include_geometry: bool = Query(True, description="Set false for a much smaller response"),
    db: Session = Depends(get_db),
):
    record = _get_file_or_404(db, file_id)
    if record.status != FileStatus.COMPLETED:
        raise ConflictError(
            f"File is {record.status}; measurements are only available for COMPLETED files."
            + (f" Reason: {record.error_message}" if record.error_message else "")
        )

    features = [
        FeatureOut(
            feature_id=f.feature_index,
            layer=f.layer,
            geometry_type=f.geometry_type,
            crs=f.crs,
            properties=f.properties,
            geometry=f.geometry if include_geometry else None,
            measurement=f.measurement,
        )
        for f in record.features
    ]
    return MeasurementsOut(
        file_id=record.id,
        filename=record.filename,
        status=record.status,
        crs=record.crs,
        feature_count=record.feature_count,
        summary=_build_summary(record.features),
        features=features,
    )


# ---------- helpers ----------

def _get_file_or_404(db: Session, file_id: str) -> UploadedFile:
    record = db.get(UploadedFile, file_id)
    if record is None:
        raise NotFoundError(f"No file found with id '{file_id}'.")
    return record


def _save_upload_to_temp(upload: UploadFile, suffix: str) -> Path:
    """Stream the upload to disk, stopping early if it exceeds the size limit.

    We never trust the Content-Length header; we count the bytes we actually read.
    """
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(suffix=suffix, dir=config.UPLOAD_DIR)
    tmp_path = Path(tmp_name)
    written = 0
    try:
        with os.fdopen(fd, "wb") as out:
            while chunk := upload.file.read(CHUNK_SIZE):
                written += len(chunk)
                if written > config.MAX_UPLOAD_BYTES:
                    raise FileTooLargeError(
                        f"File exceeds the {config.MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit."
                    )
                out.write(chunk)
        if written == 0:
            raise InvalidFileError("The uploaded file is empty.")
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    return tmp_path


def _build_summary(features) -> dict:
    """File-level totals plus a count of features per measurement status."""
    status_counts: dict[str, int] = {}
    total_area = 0.0
    total_length = 0.0
    for f in features:
        m = f.measurement or {}
        status = m.get("status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        total_area += m.get("area_sq_m", 0.0)
        total_length += m.get("length_m", 0.0)
    return {
        "status_counts": status_counts,
        "total_area_sq_m": round(total_area, 4),
        "total_length_m": round(total_length, 4),
    }