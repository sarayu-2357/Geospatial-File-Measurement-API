import pytest

from app import config
from tests.fixtures_builder import make_kml, make_shapefile_zip


def _upload(client, path, name=None, content_type="application/octet-stream"):
    return client.post(
        "/api/files/",
        files={"file": (name or path.name, path.read_bytes(), content_type)},
    )


def test_upload_kml_returns_201_and_file_info(client, tmp_path):
    resp = _upload(client, make_kml(tmp_path / "survey.kml"))
    assert resp.status_code == 201
    body = resp.json()
    assert body["filename"] == "survey.kml"
    assert body["status"] == "COMPLETED"
    assert body["feature_count"] == 3
    assert body["crs"] == "EPSG:4326"
    assert body["id"]


def test_upload_shapefile_zip(client, tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    resp = _upload(client, make_shapefile_zip(src))
    assert resp.status_code == 201
    assert resp.json()["feature_count"] == 2


def test_get_file_info(client, tmp_path):
    file_id = _upload(client, make_kml(tmp_path / "survey.kml")).json()["id"]
    resp = client.get(f"/api/files/{file_id}/")
    assert resp.status_code == 200
    assert resp.json()["id"] == file_id
    assert resp.json()["status"] == "COMPLETED"


def test_measurements_endpoint(client, tmp_path):
    file_id = _upload(client, make_kml(tmp_path / "survey.kml")).json()["id"]
    resp = client.get(f"/api/files/{file_id}/measurements/")
    assert resp.status_code == 200
    body = resp.json()

    assert body["feature_count"] == 3
    by_type = {f["geometry_type"]: f for f in body["features"]}
    assert by_type["Polygon"]["measurement"]["area_sq_m"] == pytest.approx(1_000_000, rel=0.005)
    assert by_type["LineString"]["measurement"]["length_m"] == pytest.approx(1000, rel=0.001)
    assert by_type["Point"]["measurement"]["status"] == "no_measurement_required"
    assert by_type["Polygon"]["crs"] == "EPSG:4326"
    assert by_type["Polygon"]["geometry"]["type"] == "Polygon"
    assert body["summary"]["status_counts"] == {"measured": 2, "no_measurement_required": 1}
    assert body["summary"]["total_area_sq_m"] == pytest.approx(1_000_000, rel=0.005)


def test_include_geometry_false_omits_geometry(client, tmp_path):
    file_id = _upload(client, make_kml(tmp_path / "survey.kml")).json()["id"]
    body = client.get(f"/api/files/{file_id}/measurements/?include_geometry=false").json()
    assert all(f["geometry"] is None for f in body["features"])


def test_unsupported_extension_returns_415(client, tmp_path):
    p = tmp_path / "notes.txt"
    p.write_text("hello")
    assert _upload(client, p).status_code == 415


def test_fake_kml_returns_422_and_saves_failed_record(client, tmp_path):
    p = tmp_path / "fake.kml"
    p.write_text("just some text")
    resp = _upload(client, p)
    assert resp.status_code == 422
    file_id = resp.json()["file_id"]
    assert file_id

    info = client.get(f"/api/files/{file_id}/").json()
    assert info["status"] == "FAILED"
    assert info["error_message"]

    # measurements for a failed file -> 409 Conflict
    assert client.get(f"/api/files/{file_id}/measurements/").status_code == 409


def test_shapefile_without_prj_returns_422_with_clear_message(client, tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    resp = _upload(client, make_shapefile_zip(src, with_prj=False))
    assert resp.status_code == 422
    assert "CRS" in resp.json()["detail"]


def test_oversized_upload_returns_413(client, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 10)
    resp = _upload(client, make_kml(tmp_path / "survey.kml"))
    assert resp.status_code == 413


def test_empty_upload_returns_422(client, tmp_path):
    p = tmp_path / "empty.kml"
    p.write_bytes(b"")
    assert _upload(client, p).status_code == 422


def test_unknown_id_returns_404(client):
    assert client.get("/api/files/does-not-exist/").status_code == 404
    assert client.get("/api/files/does-not-exist/measurements/").status_code == 404


def test_missing_file_field_returns_422(client):
    assert client.post("/api/files/").status_code == 422

def test_created_at_is_marked_utc_on_upload_and_on_get(client, tmp_path):
    uploaded = _upload(client, make_kml(tmp_path / "survey.kml")).json()
    fetched = client.get(f"/api/files/{uploaded['id']}/").json()
    assert uploaded["created_at"].endswith("Z")
    assert fetched["created_at"].endswith("Z")