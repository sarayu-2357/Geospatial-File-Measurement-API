# Geospatial File Measurement API

A FastAPI service that accepts a **KML** file or a **ZIP containing a Shapefile**, extracts every
feature, and returns per-feature **area** (polygons) and **length** (lines). Measurements are
calculated in metres in a projected coordinate system, never in raw latitude/longitude degrees, and
every result is cross-checked against a geodesic calculation on the WGS84 ellipsoid.

## Features

- Upload `.kml` or `.zip` (Shapefile) through one endpoint; processing is synchronous.
- Per feature: ID/index, geometry type, GeoJSON geometry, CRS, and properties.
- Area for Polygon/MultiPolygon, length for LineString/MultiLineString, no measurement for Points.
- Each feature is projected to the UTM zone of its own centroid, then compared with the geodesic value. The result reports the percentage difference and a `high`/`low` accuracy flag.
- Graceful handling of invalid geometries (repaired), empty geometries, unsupported types, missing CRS, fake or corrupt files, and unsafe ZIPs.
- `MultiGeometry` (GeometryCollection) features are split and their polygon and line parts measured.
- SQLite storage, structured logging, and 62 automated tests.

## Tech stack

FastAPI, SQLAlchemy 2 + SQLite, pyogrio (GDAL) for reading files, Shapely 2 for geometry, pyproj for
CRS transforms and geodesic maths, pytest.

## Project layout

```
app/
  main.py            app creation, startup, logging, error-to-JSON handler
  config.py          limits and settings
  db.py              SQLAlchemy engine and request-scoped sessions
  models.py          UploadedFile and FeatureRecord tables
  schemas.py         API response shapes
  errors.py          custom exceptions, each mapped to an HTTP status
  api/files.py       the three endpoints (kept thin)
  services/
    ingestion.py     validate, safely unzip, read features
    crs.py           CRS parsing, UTM zone choice, reprojection
    measurement.py   area/length plus geodesic cross-check
    processor.py     orchestrates ingestion, measurement and saving
tests/               unit tests per module, API tests, generated fixtures
samples/             survey.kml, polys.zip, lines.zip, points.zip
requirements.txt     runtime dependencies (pinned)
requirements-dev.txt test dependencies (includes requirements.txt)
```

## Setup

Developed and tested on **Python 3.13 on Windows**. Python 3.10 or newer is expected to work but has
not been tested.

**Windows (PowerShell)**

```powershell
git clone https://github.com/<your-username>/geo-measurement-api.git
cd geo-measurement-api
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If PowerShell blocks activation, run `Set-ExecutionPolicy -Scope Process Bypass` in that terminal and
activate again.

**macOS / Linux** (same steps, not tested by the author)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
uvicorn app.main:app --reload
```

The service listens at `http://127.0.0.1:8000`. Interactive docs are at
[/docs](http://127.0.0.1:8000/docs).

On first startup the app creates `geo.db` and an `uploads/` folder in the project root. Each original
upload is kept at `uploads/<file-id>/original.kml` or `original.zip`. Both are git-ignored.

## Run the tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Expected: **62 passed**. The tests use temporary databases and upload folders, never your local
`geo.db` or `uploads/`. One third-party deprecation notice (starlette/httpx) still appears in the
output; it comes from library code.

## API

All routes are under `/api/files`. Uploads use `multipart/form-data` with a required form field named
`file`. Sample inputs are in `samples/`.

### `POST /api/files/`: upload and process

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/files/" -F "file=@samples/survey.kml"
```

(On macOS/Linux use `curl` instead of `curl.exe`.)

`201 Created`. The `id` and `created_at` will differ on your machine:

```json
{
  "id": "8c81f7e3-7e66-4748-90db-986f7ad13e22",
  "filename": "survey.kml",
  "status": "COMPLETED",
  "crs": "EPSG:4326",
  "feature_count": 3,
  "error_message": null,
  "created_at": "2026-10-11T08:25:00Z"
}
```

`status` is `PROCESSING`, `COMPLETED` or `FAILED`. Timestamps are UTC. Use the returned `id` below.

### `GET /api/files/{file_id}/`: file metadata and status

```powershell
curl.exe "http://127.0.0.1:8000/api/files/8c81f7e3-7e66-4748-90db-986f7ad13e22/"
```

Returns the same shape as the upload response. A file that failed validation after being accepted is
stored as `FAILED` with an `error_message`, and can be looked up here.

### `GET /api/files/{file_id}/measurements/`: per-feature measurements

Optional query parameter `include_geometry` (default `true`). Set it to `false` to return
`"geometry": null` for each feature and get a smaller response.

```powershell
curl.exe "http://127.0.0.1:8000/api/files/8c81f7e3-7e66-4748-90db-986f7ad13e22/measurements/?include_geometry=false"
```

`200 OK`, produced from `samples/survey.kml`:

```json
{
  "file_id": "8c81f7e3-7e66-4748-90db-986f7ad13e22",
  "filename": "survey.kml",
  "status": "COMPLETED",
  "crs": "EPSG:4326",
  "feature_count": 3,
  "summary": {
    "status_counts": { "measured": 2, "no_measurement_required": 1 },
    "total_area_sq_m": 1177227.6803,
    "total_length_m": 1063.1473
  },
  "features": [
    {
      "feature_id": 0,
      "layer": "survey",
      "geometry_type": "Polygon",
      "crs": "EPSG:4326",
      "properties": { "Name": "Test Polygon", "type": "plot" },
      "geometry": null,
      "measurement": {
        "status": "measured",
        "repaired": false,
        "method": "projected_utm",
        "projected_crs": "EPSG:32644",
        "area_sq_m": 1177227.6803,
        "area_sq_km": 1.177228,
        "area_hectares": 117.7228,
        "geodesic_area_sq_m": 1175957.5032,
        "diff_pct": 0.108,
        "accuracy": "high"
      }
    },
    {
      "feature_id": 1,
      "layer": "survey",
      "geometry_type": "LineString",
      "crs": "EPSG:4326",
      "properties": { "Name": "Test Line" },
      "geometry": null,
      "measurement": {
        "status": "measured",
        "repaired": false,
        "method": "projected_utm",
        "projected_crs": "EPSG:32644",
        "length_m": 1063.1473,
        "length_km": 1.063147,
        "geodesic_length_m": 1062.5736,
        "diff_pct": 0.054,
        "accuracy": "high"
      }
    },
    {
      "feature_id": 2,
      "layer": "survey",
      "geometry_type": "Point",
      "crs": "EPSG:4326",
      "properties": { "Name": "Test Point" },
      "geometry": null,
      "measurement": {
        "status": "no_measurement_required",
        "reason": "Points have no area or length"
      }
    }
  ]
}
```

Measurement fields depend on the geometry type:

- Polygons and multipolygons include `area_sq_m`, `area_sq_km`, `area_hectares` and `geodesic_area_sq_m`.
- Lines and multilines include `length_m`, `length_km` and `geodesic_length_m`.
- Measured results also include the projected CRS, `diff_pct`, and the `high`/`low` accuracy flag.
- Every feature has a `measurement.status`: `measured`, `no_measurement_required`, `skipped`,
  `unsupported` or `error`. The last three include a `reason`.
- A GeometryCollection (for example a KML `MultiGeometry`) containing polygons and/or lines can return
  both area and length.
- Returned geometries stay in their **original** coordinates. Use each feature's `crs` to interpret them.

### Errors and limits

Errors raised by this API return `{"detail": "...", "file_id": "..."}`. `file_id` is `null` when no
record was created. When a file was accepted and then failed, it is the id of the saved `FAILED` record.
FastAPI's own request-validation errors (for example a missing `file` field) use FastAPI's standard
list-style `detail` instead.

| Status | Meaning |
| --- | --- |
| `404` | No file exists with that id. |
| `409` | Measurements requested for a file that is not `COMPLETED`. The message includes the failure reason. |
| `413` | Upload exceeds the 50 MiB limit. |
| `415` | Extension is not `.kml` or `.zip`. No record is created. |
| `422` | Empty upload, fake or corrupt file, ZIP with no `.shp`, missing or unreadable CRS, or no features. Also used for FastAPI request validation. |

ZIP archives are also rejected if they contain more than 100 members, expand beyond 200 MiB, contain a
path that escapes the extraction folder, or have no `.shp` file. A Shapefile must include its `.prj`.

## Architecture

### File-processing flow

1. The endpoint checks the extension and streams the upload to a temporary file in 1 MiB chunks,
   counting real bytes against the size limit.
2. The processor creates an `UploadedFile` row as `PROCESSING` and moves the upload to
   `uploads/<uuid>/`. The client's filename is never used as a path.
3. Ingestion checks that the content matches the extension, extracts ZIPs only after the safety checks,
   reads every layer, and detects each feature's CRS. For KML it drops GDAL's empty boilerplate columns,
   and it replaces the internal stored-file layer name with the uploaded filename.
4. Each feature is measured independently inside its own error handling and saved with its original
   GeoJSON geometry, properties and measurement.
5. The file is marked `COMPLETED`, or `FAILED` with an error message. A failure on one feature is recorded
   on that feature only.

The endpoints are plain `def`, so FastAPI runs them in its worker thread pool and the blocking
processing does not freeze the event loop.

### Measurement flow

1. Reproject the feature to WGS84 (a no-op for EPSG:4326 files), so geographic and projected inputs share
   one pipeline.
2. Repair invalid polygons with `make_valid` and report `repaired: true`. Z values are ignored.
3. Choose the UTM zone from the feature's centroid (UPS beyond 84°N and 80°S) and project to it.
4. Read `.area` or `.length` from the projected geometry. This is the reported value.
5. Compute the same quantity on the WGS84 ellipsoid with `pyproj.Geod` as a cross-check.
6. Report `diff_pct`. At or below 0.3% the result is `high` accuracy, above that it is `low`. The
   threshold is `ACCURACY_THRESHOLD_PCT` in `app/config.py`.

Empty geometries are skipped, out-of-range coordinates return an `error` status, and unsupported types
return `unsupported` with a reason. A last-resort `try/except` means one feature can never cause a `500`.

### CRS handling

- **KML** is EPSG:4326 by specification, so it is assumed when the driver gives no CRS.
- **Shapefile** CRS comes from the `.prj`. If it is missing or unreadable the upload is **rejected with
  422** instead of guessed, because assuming the wrong unit gives results wrong by orders of magnitude.
- The file-level `crs` is a single label when all features share a CRS, or `MIXED: ...` otherwise.
- Transforms use `always_xy=True` so coordinates are always (longitude, latitude). Transformers are cached
  per request and never shared between requests.

## Design decisions

| Decision | Alternative considered | Why |
| --- | --- | --- |
| Projected UTM value as primary, geodesic alongside | Geodesic only | The brief asks for measurement in a projected CRS. The geodesic value is the more faithful number, so it is reported next to it and the gap is visible. |
| UTM zone per feature (by centroid) | One CRS for the whole file, or one equal-area CRS such as EPSG:6933 | A file can span several zones, and a fixed CRS would suit some features poorly. |
| Web Mercator rejected | EPSG:3857 | It inflates area badly away from the equator. |
| Synchronous processing | Background job queue | Files are small and the client gets a final status immediately. The `status` field and the `processor` boundary make moving to async a small change. |
| Reject Shapefiles with no `.prj` | Assume EPSG:4326 | A wrong guess fails silently. |
| Save `FAILED` records for files that fail after acceptance | Store nothing on failure | The client gets an immediate error and can still look the failure up by `file_id`. |
| Per-feature status | Fail the whole file on one bad feature | One bad feature should not discard valid results. |
| pyogrio + Shapely | GeoPandas | Lighter, and no DataFrames are needed. |
| SQLite + local disk | Postgres/PostGIS + object storage | Lightweight local setup. A server database and object storage suit multi-instance deployments. |
| Overlapping polygons in one MultiGeometry are merged | Sum every part | An overlap is counted once. |
| Original geometry preserved in responses | Return WGS84 geometry | Keeps the input's coordinate semantics. Clients can omit geometry with `include_geometry=false`. |
| Dependencies pinned, with a separate dev file | One unpinned file | Reviewers install the versions that were tested, without needing test tools to run the app. |

## Known limitations

- Processing is synchronous, so very large files hold the request open.
- A file left in `PROCESSING` because the server crashed mid-request is never cleaned up.
- `/measurements/` has no pagination.
- Only vertices are projected, so very long straight edges follow a straight line in UTM rather than a great circle.
- Features crossing the antimeridian (±180°) are not handled specially.
- UTM distortion grows with distance from a zone's central meridian. In `samples/survey.kml`, about 2.6° from
  the central meridian of zone 44, the projected area was 0.108% above the geodesic value.
- ZIP size limits rely on the sizes declared in the archive header.
- KMZ is not accepted, and no authentication is implemented.
- Errors come in two shapes (this API's `detail` string with `file_id`, and FastAPI's list-style `detail`).
- Error responses (404, 409, 413, 415) work but are not declared in the OpenAPI schema, so `/docs` marks
  them "Undocumented".
- Tested on Windows with Python 3.13 only.

## Learnings

- **Degrees cannot be measured.** A 0.01° box at 17.4°N is about 1,062 m by 1,106 m, not a square, because a
  degree of longitude shrinks away from the equator.
- **Projections distort.** UTM zone 44 overstated my sample polygon by 0.108% because it sits away from the
  zone's central meridian. That is why I report a geodesic value alongside the projected one.
- **Design for partial failure.** Each feature carries its own status, so one bad feature never fails a file.
- **Two kinds of failed upload.** Rejections before a record exists return `file_id: null`. Failures after
  acceptance are saved as `FAILED` and can be queried, and `/measurements/` answers `409` for them. I checked
  both against the running server.
- **Real KML is noisy.** GDAL adds many empty boilerplate columns and names the layer after the stored
  filename, so I filter the columns and substitute the uploaded filename.
- **Upload security.** Extension and content checks, size counted on real bytes, zip-slip and zip-bomb guards,
  and never using the client's filename on disk.
- **Verify beyond the test suite.** In-process tests passing did not replace checking the live server. Testing
  with shapes of known size (a 1 km square) and a hand calculation made the results trustworthy.

## Future scope

- Background processing (Celery/RQ) with a polling endpoint and progress for large files.
- Pagination and filtering on `/measurements/`.
- Densify edges before projecting long features.
- Antimeridian handling.
- PostGIS for spatial queries; GeoPackage, GeoJSON and KMZ input.
- A `?crs=` override for Shapefiles with a missing `.prj`.
- Declare error responses in the OpenAPI schema; unify the two error shapes.
- Authentication and object storage (for example S3) for uploads.