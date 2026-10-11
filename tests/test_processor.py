import pytest
from sqlalchemy import select

from app import config
from app.errors import MissingCRSError, UnsupportedFormatError
from app.models import FeatureRecord, FileStatus, UploadedFile
from app.services import processor
from app.services.processor import process_upload
from tests.fixtures_builder import make_kml, make_shapefile_zip


def test_kml_is_processed_and_saved(db, tmp_path):
    kml = make_kml(tmp_path / "survey.kml")
    record = process_upload(db, kml, "survey.kml")

    assert record.status == FileStatus.COMPLETED
    assert record.feature_count == 3
    assert record.crs == "EPSG:4326"

    rows = db.scalars(select(FeatureRecord).where(FeatureRecord.file_id == record.id)).all()
    assert len(rows) == 3
    polygon = next(r for r in rows if r.geometry_type == "Polygon")
    assert polygon.measurement["status"] == "measured"
    assert polygon.measurement["area_sq_m"] == pytest.approx(1_000_000, rel=0.005)
    assert polygon.geometry["type"] == "Polygon"
    point = next(r for r in rows if r.geometry_type == "Point")
    assert point.measurement["status"] == "no_measurement_required"


def test_shapefile_zip_is_processed(db, tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    zip_path = make_shapefile_zip(src)
    record = process_upload(db, zip_path, "plots.zip")

    assert record.status == FileStatus.COMPLETED
    assert record.feature_count == 2
    assert record.features[0].properties["name"] == "Plot A"


def test_original_upload_is_kept_on_disk(db, tmp_path):
    kml = make_kml(tmp_path / "survey.kml")
    record = process_upload(db, kml, "survey.kml")
    assert (config.UPLOAD_DIR / record.id / "original.kml").exists()


def test_missing_prj_saves_a_failed_record(db, tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    zip_path = make_shapefile_zip(src, with_prj=False)

    with pytest.raises(MissingCRSError) as excinfo:
        process_upload(db, zip_path, "plots.zip")

    saved = db.get(UploadedFile, excinfo.value.file_id)
    assert saved.status == FileStatus.FAILED
    assert "CRS" in saved.error_message


def test_bad_extension_creates_no_record(db, tmp_path):
    exe = tmp_path / "virus.exe"
    exe.write_bytes(b"MZ")
    with pytest.raises(UnsupportedFormatError):
        process_upload(db, exe, "virus.exe")
    assert db.scalars(select(UploadedFile)).all() == []


def test_one_failing_feature_does_not_fail_the_file(db, tmp_path, monkeypatch):
    """Simulate a crash while handling the LineString; the other two must survive."""
    real = processor.reproject_to_wgs84

    def flaky(geom, crs):
        if geom.geom_type == "LineString":
            raise RuntimeError("boom")
        return real(geom, crs)

    monkeypatch.setattr(processor, "reproject_to_wgs84", flaky)

    kml = make_kml(tmp_path / "survey.kml")
    record = process_upload(db, kml, "survey.kml")

    assert record.status == FileStatus.COMPLETED
    by_type = {r.geometry_type: r.measurement for r in record.features}
    assert by_type["LineString"]["status"] == "error"
    assert "boom" in by_type["LineString"]["reason"]
    assert by_type["Polygon"]["status"] == "measured"
    assert by_type["Point"]["status"] == "no_measurement_required"