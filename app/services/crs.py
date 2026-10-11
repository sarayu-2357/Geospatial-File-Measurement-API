"""CRS helpers: validate a CRS, pick a UTM zone, build transformers."""
import numpy as np
import shapely
from pyproj import CRS, Transformer
from pyproj.exceptions import CRSError
from shapely.geometry.base import BaseGeometry

from app.errors import InvalidFileError, MissingCRSError


def utm_epsg_for(lon: float, lat: float) -> int:
    """Return the EPSG code of the UTM zone containing (lon, lat).

    Zones are 6 degrees wide, numbered 1..60 starting at longitude -180.
    North of the equator the code is 326xx, south it is 327xx.
    Beyond UTM's range (>=84N or <=80S) we use the polar UPS systems.
    """
    if lat >= 84:
        return 32661   # UPS North
    if lat <= -80:
        return 32761   # UPS South
    zone = int((lon + 180) // 6) + 1
    zone = min(max(zone, 1), 60)          # lon == 180 would give 61
    return (32600 if lat >= 0 else 32700) + zone


def resolve_crs(crs_input) -> CRS:
    """Turn whatever GDAL gave us (EPSG string or WKT text) into a CRS object."""
    if crs_input is None or not str(crs_input).strip():
        raise MissingCRSError(
            "The file has no CRS information (for shapefiles, the .prj file is missing)."
        )
    try:
        return CRS.from_user_input(crs_input)
    except CRSError as exc:
        raise InvalidFileError(f"Could not understand the file's CRS: {exc}") from exc


def crs_label(crs: CRS) -> str:
    """Short human label like 'EPSG:4326', or the CRS name if it has no EPSG code."""
    epsg = crs.to_epsg()
    return f"EPSG:{epsg}" if epsg else crs.name


def get_transformer(epsg: int, cache: dict | None = None) -> Transformer:
    """WGS84 lon/lat -> the given projected CRS (metres).

    `cache` is a plain dict owned by ONE request. Building a transformer is
    slowish, so we reuse it across features, but we never share it between
    requests because pyproj transformers are not guaranteed thread-safe.
    """
    if cache is not None and epsg in cache:
        return cache[epsg]
    transformer = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    if cache is not None:
        cache[epsg] = transformer
    return transformer


def transform_geometry(geom: BaseGeometry, transformer: Transformer) -> BaseGeometry:
    """Apply a pyproj transformer to every vertex of a Shapely geometry.

    shapely.transform hands us an (N, 2) array of x/y pairs; we convert them
    in one vectorised call and return an (N, 2) array. Z values are dropped,
    which is fine because we only measure in 2D.
    """
    def _apply(coords):
        x, y = transformer.transform(coords[:, 0], coords[:, 1])
        return np.column_stack([x, y])

    return shapely.transform(geom, _apply)


def reproject_to_wgs84(geom: BaseGeometry, source_crs: CRS) -> BaseGeometry:
    """Convert a geometry from its file CRS into WGS84 lon/lat.

    Doing this first means every file, geographic or projected, goes through
    the same measurement pipeline.
    """
    if source_crs.to_epsg() == 4326:
        return geom
    transformer = Transformer.from_crs(source_crs, "EPSG:4326", always_xy=True)
    return transform_geometry(geom, transformer)