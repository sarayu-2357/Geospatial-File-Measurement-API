"""Builds tiny geospatial test files from code.

Why: tests should use shapes whose true size we KNOW (e.g. a 1 km x 1 km
square), so a passing test proves the maths is right.
"""
import zipfile
from pathlib import Path

import shapefile  # pyshp
from pyproj import CRS, Geod
from pyproj.enums import WktVersion

_GEOD = Geod(ellps="WGS84")


def square_around(lon: float, lat: float, side_m: float = 1000.0):
    """Return a closed ring (list of (lon, lat)) for a ~side_m x side_m square.

    We walk on the real Earth: east side_m metres, north side_m metres,
    then back. So the true area is ~side_m**2 square metres.
    """
    lon1, lat1, _ = _GEOD.fwd(lon, lat, 90, side_m)    # go east
    lon2, lat2, _ = _GEOD.fwd(lon1, lat1, 0, side_m)   # then north
    lon3, lat3, _ = _GEOD.fwd(lon, lat, 0, side_m)     # north from start
    return [(lon, lat), (lon1, lat1), (lon2, lat2), (lon3, lat3), (lon, lat)]


def make_kml(path: Path, lon: float = 79.6, lat: float = 18.0) -> Path:
    """Write a KML with one polygon, one line (1000 m long) and one point."""
    ring = square_around(lon, lat)
    poly_coords = " ".join(f"{x},{y},0" for x, y in ring)
    east_lon, east_lat, _ = _GEOD.fwd(lon, lat, 90, 1000)
    kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Survey</name>
    <Placemark>
      <name>Plot A</name>
      <Polygon><outerBoundaryIs><LinearRing>
        <coordinates>{poly_coords}</coordinates>
      </LinearRing></outerBoundaryIs></Polygon>
    </Placemark>
    <Placemark>
      <name>Road 1</name>
      <LineString><coordinates>{lon},{lat},0 {east_lon},{east_lat},0</coordinates></LineString>
    </Placemark>
    <Placemark>
      <name>Well 1</name>
      <Point><coordinates>{lon},{lat},0</coordinates></Point>
    </Placemark>
  </Document>
</kml>"""
    path.write_text(kml, encoding="utf-8")
    return path


def make_shapefile_zip(folder: Path, name: str = "plots", with_prj: bool = True) -> Path:
    """Write a 2-polygon shapefile into `folder` and zip it. Returns the zip path."""
    base = folder / name
    plots = [("Plot A", 79.60, 18.0), ("Plot B", 79.65, 18.0)]
    with shapefile.Writer(str(base), shapeType=shapefile.POLYGON) as w:
        w.field("name", "C", 40)
        w.field("owner", "C", 40)
        for label, lo, la in plots:
            # Shapefile outer rings must be clockwise, so we reverse ours.
            ring = list(reversed(square_around(lo, la)))
            w.poly([ring])
            w.record(label, "Alice")

    if with_prj:
        prj_text = CRS.from_epsg(4326).to_wkt(WktVersion.WKT1_ESRI)
        (folder / f"{name}.prj").write_text(prj_text)

    zip_path = folder / f"{name}.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for ext in (".shp", ".shx", ".dbf", ".prj"):
            f = folder / f"{name}{ext}"
            if f.exists():
                zf.write(f, arcname=f.name)
    return zip_path


def make_projected_shapefile_zip(folder: Path, name: str = "utm_plots") -> Path:
    """A shapefile whose coordinates are METRES in UTM zone 44N (EPSG:32644)."""
    base = folder / name
    with shapefile.Writer(str(base), shapeType=shapefile.POLYGON) as w:
        w.field("name", "C", 40)
        # 1000 m x 1000 m, clockwise
        w.poly([[(500000, 2000000), (500000, 2001000), (501000, 2001000),
                 (501000, 2000000), (500000, 2000000)]])
        w.record("UTM Plot")
    prj_text = CRS.from_epsg(32644).to_wkt(WktVersion.WKT1_ESRI)
    (folder / f"{name}.prj").write_text(prj_text)

    zip_path = folder / f"{name}.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for ext in (".shp", ".shx", ".dbf", ".prj"):
            zf.write(folder / f"{name}{ext}", arcname=f"{name}{ext}")
    return zip_path


def make_multilayer_kml(path: Path, lon: float = 79.6, lat: float = 18.0) -> Path:
    """A KML with two <Folder>s; GDAL exposes each folder as a separate layer."""
    kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Folder><name>Wells A</name>
      <Placemark><name>W1</name><Point><coordinates>{lon},{lat},0</coordinates></Point></Placemark>
    </Folder>
    <Folder><name>Wells B</name>
      <Placemark><name>W2</name><Point><coordinates>{lon + 0.01},{lat},0</coordinates></Point></Placemark>
    </Folder>
  </Document>
</kml>"""
    path.write_text(kml, encoding="utf-8")
    return path


def make_multigeometry_kml(path: Path, lon: float = 79.6, lat: float = 18.0) -> Path:
    """One Placemark holding a 1 km square AND a 1 km line (a <MultiGeometry>)."""
    ring = square_around(lon, lat)
    poly_coords = " ".join(f"{x},{y},0" for x, y in ring)
    line_lon = lon + 0.05
    end_lon, end_lat, _ = _GEOD.fwd(line_lon, lat, 90, 1000)
    kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>Mixed</name>
      <MultiGeometry>
        <Polygon><outerBoundaryIs><LinearRing>
          <coordinates>{poly_coords}</coordinates>
        </LinearRing></outerBoundaryIs></Polygon>
        <LineString><coordinates>{line_lon},{lat},0 {end_lon},{end_lat},0</coordinates></LineString>
      </MultiGeometry>
    </Placemark>
  </Document>
</kml>"""
    path.write_text(kml, encoding="utf-8")
    return path