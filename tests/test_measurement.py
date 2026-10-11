import pytest
from pyproj import Geod
from shapely.geometry import GeometryCollection, LineString, MultiPolygon, Point, Polygon

from app.services.crs import reproject_to_wgs84, resolve_crs
from app.services.measurement import measure_geometry
from tests.fixtures_builder import square_around

GEOD = Geod(ellps="WGS84")
LON, LAT = 79.6, 18.0


def test_naive_area_in_degrees_is_meaningless():
    """THE point of the assignment: raw degree maths gives nonsense."""
    naive = Polygon(square_around(LON, LAT)).area
    assert naive < 0.001            # ~0.00008 "square degrees", not ~1,000,000 m2


def test_one_km_square_is_about_one_million_sq_m():
    result = measure_geometry(Polygon(square_around(LON, LAT)))
    assert result["status"] == "measured"
    assert result["area_sq_m"] == pytest.approx(1_000_000, rel=0.005)
    assert result["geodesic_area_sq_m"] == pytest.approx(1_000_000, rel=0.005)
    assert result["projected_crs"] == "EPSG:32644"
    assert result["accuracy"] == "high"


def test_one_km_square_at_60_north():
    result = measure_geometry(Polygon(square_around(10.0, 60.0)))
    assert result["area_sq_m"] == pytest.approx(1_000_000, rel=0.005)


def test_line_length_is_1000_m():
    east_lon, east_lat, _ = GEOD.fwd(LON, LAT, 90, 1000)
    result = measure_geometry(LineString([(LON, LAT), (east_lon, east_lat)]))
    assert result["status"] == "measured"
    assert result["length_m"] == pytest.approx(1000, rel=0.001)
    assert result["geodesic_length_m"] == pytest.approx(1000, rel=0.001)


def test_polygon_with_hole_subtracts_hole():
    outer = square_around(LON, LAT, 2000)                       # 4 km2
    lon1, lat1, _ = GEOD.fwd(LON, LAT, 90, 500)
    lon2, lat2, _ = GEOD.fwd(lon1, lat1, 0, 500)
    hole = square_around(lon2, lat2, 1000)                      # 1 km2
    result = measure_geometry(Polygon(outer, [hole]))
    assert result["area_sq_m"] == pytest.approx(3_000_000, rel=0.005)
    assert result["geodesic_area_sq_m"] == pytest.approx(3_000_000, rel=0.005)


def test_multipolygon_sums_parts():
    a = Polygon(square_around(LON, LAT))
    b = Polygon(square_around(LON + 0.1, LAT))
    result = measure_geometry(MultiPolygon([a, b]))
    assert result["area_sq_m"] == pytest.approx(2_000_000, rel=0.005)


def test_point_needs_no_measurement():
    assert measure_geometry(Point(LON, LAT))["status"] == "no_measurement_required"


def test_empty_geometry_is_skipped():
    assert measure_geometry(Polygon())["status"] == "skipped"
    assert measure_geometry(None)["status"] == "skipped"


def test_geometry_collection_is_unsupported_not_a_crash():
    result = measure_geometry(GeometryCollection([Point(LON, LAT)]))
    assert result["status"] == "unsupported"
    assert "GeometryCollection" in result["reason"]


def test_bowtie_is_repaired_and_measured():
    bowtie = Polygon([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)])
    assert not bowtie.is_valid
    result = measure_geometry(bowtie)
    assert result["status"] == "measured"
    assert result["repaired"] is True
    assert 5_000 < result["area_sq_km"] < 7_000      # two triangles, ~half of a 1-degree square


def test_z_coordinates_are_ignored():
    poly = Polygon([(x, y, 0.0) for x, y in square_around(LON, LAT)])
    assert measure_geometry(poly)["area_sq_m"] == pytest.approx(1_000_000, rel=0.005)


def test_out_of_range_coordinates_return_error_status():
    result = measure_geometry(Polygon([(200, 0), (201, 0), (201, 1), (200, 1)]))
    assert result["status"] == "error"
    assert "range" in result["reason"]


def test_projected_input_pipeline_end_to_end():
    """A 1000 m x 1000 m square drawn in UTM metres -> WGS84 -> measured."""
    crs = resolve_crs("EPSG:32644")
    square = Polygon([(500000, 2000000), (501000, 2000000), (501000, 2001000), (500000, 2001000)])
    result = measure_geometry(reproject_to_wgs84(square, crs))
    assert result["area_sq_m"] == pytest.approx(1_000_000, rel=0.001)
    assert result["diff_pct"] < 0.2     # UTM scale factor 0.9996 -> ~0.08% grid-vs-ground gap


def test_huge_feature_is_flagged_low_accuracy():
    """~30x30 degree polygon: one projection is a poor fit, so the cross-check should flag it.
    (If this fails, it's a tolerance question rather than a bug. Send me the printed numbers.)"""
    huge = Polygon([(0, 0), (30, 0), (30, 30), (0, 30), (0, 0)])
    assert measure_geometry(huge)["accuracy"] == "low"