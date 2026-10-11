"""Area and length calculation.

Strategy:
  1. PRIMARY: project the feature to the UTM zone of its centroid (metres)
     and read .area / .length.
  2. CROSS-CHECK: compute the same thing geodesically on the WGS84 ellipsoid.
  3. Report the % difference and flag 'low' accuracy if it is large.

Input geometries must already be WGS84 lon/lat.
Nothing in here may raise: bad features come back as a status + reason.
"""
import logging

import shapely
from pyproj import Geod
from shapely.geometry.base import BaseGeometry

from app.config import ACCURACY_THRESHOLD_PCT
from app.services.crs import get_transformer, transform_geometry, utm_epsg_for

logger = logging.getLogger(__name__)

_GEOD = Geod(ellps="WGS84")

POLYGON_TYPES = {"Polygon", "MultiPolygon"}
LINE_TYPES = {"LineString", "MultiLineString"}
POINT_TYPES = {"Point", "MultiPoint"}


def measure_geometry(geom: BaseGeometry | None, transformer_cache: dict | None = None) -> dict:
    """Public entry point. Always returns a dict with a 'status' key:
    measured | no_measurement_required | skipped | unsupported | error
    """
    try:
        return _measure(geom, transformer_cache)
    except Exception as exc:  # last-resort safety net: one bad feature must not kill the file
        logger.exception("Unexpected error while measuring a geometry")
        return {"status": "error", "reason": f"Measurement failed: {exc}"}


def _measure(geom, cache) -> dict:
    if geom is None or geom.is_empty:
        return {"status": "skipped", "reason": "Geometry is empty or missing"}

    geom = shapely.force_2d(geom)       # drop Z; height is irrelevant for area/length
    gtype = geom.geom_type

    if gtype in POINT_TYPES:
        return {"status": "no_measurement_required", "reason": "Points have no area or length"}
    if gtype != "GeometryCollection" and gtype not in POLYGON_TYPES | LINE_TYPES:
        return {
            "status": "unsupported",
            "reason": f"Geometry type '{gtype}' is not supported for measurement",
        }

    minx, miny, maxx, maxy = geom.bounds
    if minx < -180 or maxx > 180 or miny < -90 or maxy > 90:
        return {"status": "error", "reason": "Coordinates are outside the valid longitude/latitude range"}

    if gtype == "GeometryCollection":
        return _measure_collection(geom, cache)
    if gtype in POLYGON_TYPES:
        return _measure_polygonal(geom, cache)
    return _measure_linear(geom, cache)

def _measure_collection(geom, cache) -> dict:
    """Handle a GeometryCollection (what KML <MultiGeometry> usually becomes).

    We pull out the polygon parts and the line parts, merge each group, and
    measure them with the normal functions. Points inside are ignored.
    If there is nothing measurable, we say so instead of crashing.
    """
    parts = [p for p in shapely.get_parts(geom) if not p.is_empty]
    polygons = [p for p in parts if p.geom_type in POLYGON_TYPES]
    lines = [p for p in parts if p.geom_type in LINE_TYPES]

    if not polygons and not lines:
        return {
            "status": "unsupported",
            "reason": "GeometryCollection contains no polygons or lines to measure",
        }

    out = {"status": "measured", "from_collection": True, "method": "projected_utm", "repaired": False}
    diffs = []

    if polygons:
        result = _measure_polygonal(shapely.union_all(polygons), cache)
        if result["status"] != "measured":
            return result
        for key in ("area_sq_m", "area_sq_km", "area_hectares", "geodesic_area_sq_m"):
            out[key] = result[key]
        out["projected_crs"] = result["projected_crs"]
        out["repaired"] = result["repaired"]
        diffs.append(result["diff_pct"])

    if lines:
        result = _measure_linear(shapely.union_all(lines), cache)
        for key in ("length_m", "length_km", "geodesic_length_m"):
            out[key] = result[key]
        out.setdefault("projected_crs", result["projected_crs"])
        diffs.append(result["diff_pct"])

    out["diff_pct"] = max(diffs)
    out["accuracy"] = "high" if out["diff_pct"] <= ACCURACY_THRESHOLD_PCT else "low"
    return out


# ---------- polygons ----------

def _measure_polygonal(geom, cache) -> dict:
    repaired = False
    if not geom.is_valid:
        geom = _keep_parts(shapely.make_valid(geom), POLYGON_TYPES)
        repaired = True
        if geom is None:
            return {"status": "skipped", "reason": "Invalid geometry; no area remained after repair"}

    projected, epsg_label = _project(geom, cache)
    projected_area = projected.area
    geodesic_area = _geodesic_area(geom)
    diff_pct, accuracy = _compare(projected_area, geodesic_area)

    return {
        "status": "measured",
        "repaired": repaired,
        "method": "projected_utm",
        "projected_crs": epsg_label,
        "area_sq_m": round(projected_area, 4),
        "area_sq_km": round(projected_area / 1e6, 6),
        "area_hectares": round(projected_area / 1e4, 4),
        "geodesic_area_sq_m": round(geodesic_area, 4),
        "diff_pct": diff_pct,
        "accuracy": accuracy,
    }


def _geodesic_area(geom) -> float:
    """Ellipsoid area: exterior ring minus holes, summed over parts."""
    total = 0.0
    for poly in shapely.get_parts(geom):
        total += abs(_ring_area(poly.exterior))
        for hole in poly.interiors:
            total -= abs(_ring_area(hole))
    return total


def _ring_area(ring) -> float:
    xs, ys = ring.xy
    area, _perimeter = _GEOD.polygon_area_perimeter(list(xs), list(ys))
    return area   # signed: sign depends on ring direction, so callers use abs()


# ---------- lines ----------

def _measure_linear(geom, cache) -> dict:
    projected, epsg_label = _project(geom, cache)
    projected_length = projected.length
    geodesic_length = sum(
        _GEOD.line_length(list(part.xy[0]), list(part.xy[1]))
        for part in shapely.get_parts(geom)
    )
    diff_pct, accuracy = _compare(projected_length, geodesic_length)

    return {
        "status": "measured",
        "repaired": False,
        "method": "projected_utm",
        "projected_crs": epsg_label,
        "length_m": round(projected_length, 4),
        "length_km": round(projected_length / 1e3, 6),
        "geodesic_length_m": round(geodesic_length, 4),
        "diff_pct": diff_pct,
        "accuracy": accuracy,
    }


# ---------- shared helpers ----------

def _project(geom, cache):
    """Project to the UTM zone of the geometry's centroid. Returns (geometry, 'EPSG:xxxxx')."""
    centroid = geom.centroid
    epsg = utm_epsg_for(centroid.x, centroid.y)
    transformer = get_transformer(epsg, cache)
    return transform_geometry(geom, transformer), f"EPSG:{epsg}"


def _keep_parts(geom, kinds):
    """After make_valid we may get a GeometryCollection; keep only the wanted shapes."""
    parts = [p for p in shapely.get_parts(geom) if p.geom_type in kinds and not p.is_empty]
    if not parts:
        return None
    return shapely.union_all(parts)


def _compare(projected: float, geodesic: float):
    diff = abs(projected - geodesic) / geodesic * 100 if geodesic else 0.0
    accuracy = "high" if diff <= ACCURACY_THRESHOLD_PCT else "low"
    return round(diff, 4), accuracy