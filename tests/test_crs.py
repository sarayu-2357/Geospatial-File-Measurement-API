import pytest
from shapely.geometry import Polygon

from app.errors import InvalidFileError, MissingCRSError
from app.services.crs import crs_label, reproject_to_wgs84, resolve_crs, utm_epsg_for


@pytest.mark.parametrize(
    "lon, lat, expected",
    [
        (79.6, 18.0, 32644),     # Warangal, India: UTM 44N
        (-0.12, 51.5, 32630),    # London: UTM 30N
        (151.2, -33.9, 32756),   # Sydney: UTM 56S
        (180.0, 10.0, 32660),    # edge: clamps to zone 60
        (0.0, 85.0, 32661),      # polar north -> UPS
        (0.0, -85.0, 32761),     # polar south -> UPS
    ],
)
def test_utm_zone_selection(lon, lat, expected):
    assert utm_epsg_for(lon, lat) == expected


def test_missing_crs_raises():
    with pytest.raises(MissingCRSError):
        resolve_crs(None)


def test_garbage_crs_raises():
    with pytest.raises(InvalidFileError):
        resolve_crs("not a crs")


def test_crs_label():
    assert crs_label(resolve_crs("EPSG:4326")) == "EPSG:4326"


def test_reproject_utm_square_to_wgs84_stays_in_range():
    crs = resolve_crs("EPSG:32644")
    square = Polygon([(500000, 2000000), (501000, 2000000), (501000, 2001000), (500000, 2001000)])
    minx, miny, maxx, maxy = reproject_to_wgs84(square, crs).bounds
    assert 80.9 < minx < 81.1       # zone 44's central meridian is 81 E
    assert 17.9 < miny < 18.3