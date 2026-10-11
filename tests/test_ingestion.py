import zipfile

import pytest

from app.errors import InvalidFileError, MissingCRSError, UnsupportedFormatError
from app.services.crs import resolve_crs
from app.services.ingestion import load_features
from tests.fixtures_builder import make_kml, make_shapefile_zip


def test_kml_loads_all_features(tmp_path):
    kml = make_kml(tmp_path / "survey.kml")
    features = load_features(kml, "survey.kml", tmp_path / "work")
    assert sorted(f.geometry.geom_type for f in features) == ["LineString", "Point", "Polygon"]
    assert [f.index for f in features] == [0, 1, 2]
    assert all(resolve_crs(f.crs).to_epsg() == 4326 for f in features)
    values = [v for f in features for v in f.properties.values()]
    assert "Plot A" in values


def test_shapefile_zip_loads_features_and_properties(tmp_path):
    zip_path = make_shapefile_zip(tmp_path / "src") if (tmp_path / "src").mkdir() is None else None
    features = load_features(zip_path, "plots.zip", tmp_path / "work")
    assert len(features) == 2
    assert all(f.geometry.geom_type == "Polygon" for f in features)
    assert features[0].properties["name"] == "Plot A"
    assert features[0].properties["owner"] == "Alice"
    assert resolve_crs(features[0].crs).to_epsg() == 4326


def test_shapefile_without_prj_raises_missing_crs(tmp_path):
    (tmp_path / "src").mkdir()
    zip_path = make_shapefile_zip(tmp_path / "src", with_prj=False)
    with pytest.raises(MissingCRSError):
        load_features(zip_path, "plots.zip", tmp_path / "work")


def test_zip_without_shp_is_rejected(tmp_path):
    p = tmp_path / "empty.zip"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("readme.txt", "hello")
    with pytest.raises(InvalidFileError, match=r"\.shp"):
        load_features(p, "empty.zip", tmp_path / "work")


def test_zip_slip_is_rejected(tmp_path):
    p = tmp_path / "evil.zip"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("../evil.txt", "x")
    with pytest.raises(InvalidFileError, match="unsafe"):
        load_features(p, "evil.zip", tmp_path / "work")
    assert not (tmp_path / "evil.txt").exists()


def test_text_file_renamed_to_kml_is_rejected(tmp_path):
    p = tmp_path / "fake.kml"
    p.write_text("just some text")
    with pytest.raises(InvalidFileError):
        load_features(p, "fake.kml", tmp_path / "work")


def test_non_zip_bytes_with_zip_extension_rejected(tmp_path):
    p = tmp_path / "fake.zip"
    p.write_bytes(b"not a zip at all")
    with pytest.raises(InvalidFileError):
        load_features(p, "fake.zip", tmp_path / "work")


def test_unsupported_extension_rejected(tmp_path):
    p = tmp_path / "virus.exe"
    p.write_bytes(b"MZ")
    with pytest.raises(UnsupportedFormatError):
        load_features(p, "virus.exe", tmp_path / "work")

    
def test_kml_properties_are_cleaned(tmp_path):
    kml = make_kml(tmp_path / "survey.kml")
    features = load_features(kml, "survey.kml", tmp_path / "work")
    for f in features:
        assert None not in f.properties.values()
        assert "tessellate" not in f.properties
        assert "visibility" not in f.properties
    assert {f.properties.get("Name") for f in features} == {"Plot A", "Road 1", "Well 1"}


def test_kml_layer_name_falls_back_to_uploaded_filename(tmp_path):
    stored = tmp_path / "original.kml"      # how the processor stores uploads
    stored.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
        "<Placemark><name>P</name><Point><coordinates>79.6,18,0</coordinates></Point></Placemark>"
        "</Document></kml>",
        encoding="utf-8",
    )
    features = load_features(stored, "my survey.kml", tmp_path / "work")
    assert {f.layer for f in features} == {"my survey"}