"""Stage 0: can this machine's GDAL read KML and Shapefile at all?"""
import pyogrio
from pyogrio.raw import read as raw_read

from tests.fixtures_builder import make_kml, make_shapefile_zip


def test_kml_driver_available():
    assert "KML" in pyogrio.list_drivers()


def test_can_read_kml(tmp_path):
    kml = make_kml(tmp_path / "survey.kml")
    total = 0
    for layer_name, _ in pyogrio.list_layers(str(kml)):
        result = raw_read(str(kml), layer=layer_name)
        total += len(result[-2])          # geometry array
    assert total == 3


def test_can_read_shapefile(tmp_path):
    make_shapefile_zip(tmp_path)
    result = raw_read(str(tmp_path / "plots.shp"))
    meta, geoms = result[0], result[-2]
    assert meta["crs"] is not None
    assert len(geoms) == 2