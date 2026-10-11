import pytest
from pyproj import Geod
from shapely.geometry import GeometryCollection, LineString, Point, Polygon

from app.models import FileStatus
from app.services.ingestion import load_features
from app.services.measurement import measure_geometry
from app.services.processor import process_upload
from tests.fixtures_builder import (
    make_multigeometry_kml,
    make_multilayer_kml,
    make_projected_shapefile_zip,
    square_around,
)

GEOD = Geod(ellps="WGS84")
LON, LAT = 79.6, 18.0


def _line_1km(lon, lat):
    end_lon, end_lat, _ = GEOD.fwd(lon, lat, 90, 1000)
    return LineString([(lon, lat), (end_lon, end_lat)])


def test_collection_with_polygon_line_and_point_is_measured():
    collection = GeometryCollection(
        [Polygon(square_around(LON, LAT)), _line_1km(LON + 0.05, LAT), Point(LON, LAT)]
    )
    result = measure_geometry(collection)
    assert result["status"] == "measured"
    assert result["from_collection"] is True
    assert result["area_sq_m"] == pytest.approx(1_000_000, rel=0.005)
    assert result["length_m"] == pytest.approx(1000, rel=0.001)


def test_collection_with_only_a_line_is_measured():
    result = measure_geometry(GeometryCollection([_line_1km(LON, LAT)]))
    assert result["status"] == "measured"
    assert result["length_m"] == pytest.approx(1000, rel=0.001)
    assert "area_sq_m" not in result


def test_collection_with_only_points_stays_unsupported():
    result = measure_geometry(GeometryCollection([Point(LON, LAT), Point(LON + 1, LAT)]))
    assert result["status"] == "unsupported"


def test_kml_multigeometry_is_measured_not_unsupported(db, tmp_path):
    kml = make_multigeometry_kml(tmp_path / "multi.kml")
    record = process_upload(db, kml, "multi.kml")
    assert record.feature_count == 1
    m = record.features[0].measurement
    assert m["status"] == "measured"
    assert m["area_sq_m"] == pytest.approx(1_000_000, rel=0.005)
    assert m["length_m"] == pytest.approx(1000, rel=0.001)


def test_kml_with_two_folders_loads_both_layers(tmp_path):
    kml = make_multilayer_kml(tmp_path / "layers.kml")
    features = load_features(kml, "layers.kml", tmp_path / "work")
    assert len(features) == 2
    assert [f.index for f in features] == [0, 1]


def test_projected_shapefile_is_measured_in_metres(db, tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    record = process_upload(db, make_projected_shapefile_zip(src), "utm_plots.zip")
    assert record.status == FileStatus.COMPLETED
    assert record.crs != "EPSG:4326"            # the file really was NOT in degrees
    m = record.features[0].measurement
    assert m["projected_crs"] == "EPSG:32644"
    assert m["area_sq_m"] == pytest.approx(1_000_000, rel=0.002)