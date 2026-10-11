"""Turn an uploaded file (.kml or .zip of a shapefile) into a list of RawFeature.

Responsibilities: validate the file, unzip safely, read every layer, and
detect each feature's CRS. It does NOT measure anything.
"""
import logging
import math
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyogrio
import shapely
from pyogrio.raw import read as raw_read

from app.config import ALLOWED_EXTENSIONS, MAX_UNCOMPRESSED_BYTES, MAX_ZIP_MEMBERS
from app.errors import InvalidFileError, MissingCRSError, UnsupportedFormatError

logger = logging.getLogger(__name__)

# Columns GDAL's KML driver adds to every feature. They are almost always empty or
# default values and bury the attributes the user actually cares about.
KML_NOISE_FIELDS = {
    "timestamp", "begin", "end", "altitudeMode", "tessellate",
    "extrude", "visibility", "drawOrder", "icon",
}

@dataclass
class RawFeature:
    index: int          # position in the file, starting at 0
    layer: str          # which layer/shapefile it came from
    geometry: object    # a shapely geometry, or None if the feature has no shape
    properties: dict    # attribute table values, JSON-safe
    crs: str            # CRS as reported by GDAL (EPSG string or WKT)


def load_features(file_path: Path, original_filename: str, workdir: Path) -> list[RawFeature]:
    """Main entry. Raises GeoAPIError subclasses for any problem with the file."""
    file_path, workdir = Path(file_path), Path(workdir)
    suffix = validate_extension(original_filename)
    validate_content(file_path, suffix)
    workdir.mkdir(parents=True, exist_ok=True)

    features: list[RawFeature] = []
    if suffix == ".kml":
        features += _read_dataset(file_path, start_index=0, assume_kml=True)
        # We store uploads as "original.kml". If the KML has no layer name of its own,
        # GDAL falls back to that internal name, so show the uploaded name instead.
        display_name = Path(original_filename).stem
        for f in features:
            if f.layer == file_path.stem:
                f.layer = display_name
    else:
        extract_zip_safely(file_path, workdir)
        shp_files = find_shapefiles(workdir)
        if not shp_files:
            raise InvalidFileError("The ZIP does not contain any .shp file.")
        for shp in shp_files:
            features += _read_dataset(shp, start_index=len(features), assume_kml=False)

    if not features:
        raise InvalidFileError("The file was readable but contains no features.")
    logger.info("Loaded %d features from %s", len(features), original_filename)
    return features


def validate_extension(filename: str) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise UnsupportedFormatError(
            f"Unsupported file type '{suffix or 'none'}'. Upload a .kml or a .zip containing a shapefile."
        )
    return suffix


def validate_content(path: Path, suffix: str) -> None:
    """Check the bytes match the extension (catches a renamed .exe or a text file)."""
    if suffix == ".zip":
        if not zipfile.is_zipfile(path):
            raise InvalidFileError("File has a .zip extension but is not a valid ZIP archive.")
    else:
        with open(path, "rb") as fh:
            head = fh.read(2048).decode("utf-8", errors="ignore").lower()
        if "<kml" not in head:
            raise InvalidFileError("File has a .kml extension but does not look like KML.")


def extract_zip_safely(zip_path: Path, dest_dir: Path) -> None:
    """Extract only if the archive passes safety checks (zip-slip, zip bomb)."""
    dest_root = Path(dest_dir).resolve()
    try:
        with zipfile.ZipFile(zip_path) as zf:
            members = zf.infolist()
            if len(members) > MAX_ZIP_MEMBERS:
                raise InvalidFileError("ZIP contains too many files.")
            if sum(m.file_size for m in members) > MAX_UNCOMPRESSED_BYTES:
                raise InvalidFileError("ZIP expands to more than the allowed size.")
            for m in members:
                target = (dest_root / m.filename).resolve()
                if not target.is_relative_to(dest_root):
                    raise InvalidFileError(f"ZIP contains an unsafe path: {m.filename}")
            zf.extractall(dest_root)
    except zipfile.BadZipFile as exc:
        raise InvalidFileError("ZIP archive is corrupted.") from exc


def find_shapefiles(folder: Path) -> list[Path]:
    """All .shp files, ignoring macOS junk like __MACOSX/._name.shp."""
    found = [
        p for p in Path(folder).rglob("*")
        if p.suffix.lower() == ".shp"
        and "__MACOSX" not in p.parts
        and not p.name.startswith("._")
    ]
    return sorted(found)


def _read_dataset(path: Path, start_index: int, assume_kml: bool) -> list[RawFeature]:
    try:
        layers = pyogrio.list_layers(str(path))
    except Exception as exc:
        raise InvalidFileError(f"Could not open '{path.name}' as a geospatial file: {exc}") from exc

    features: list[RawFeature] = []
    for layer_name, _geom_type in layers:
        try:
            result = raw_read(str(path), layer=layer_name)
        except Exception as exc:
            raise InvalidFileError(f"Could not read layer '{layer_name}': {exc}") from exc

        # Index from the end so this works whether the tuple has 3 or 4 items.
        meta, geoms, field_data = result[0], result[-2], result[-1]
        if len(geoms) == 0:
            continue                          # empty KML folder: nothing to read

        crs = meta.get("crs")
        if crs is None:
            if assume_kml:
                crs = "EPSG:4326"             # the KML specification guarantees this
            else:
                raise MissingCRSError(
                    f"'{path.name}' has no CRS information (the .prj file is missing)."
                )

        geometries = shapely.from_wkb(geoms)
        names = list(meta["fields"])
        for i, geom in enumerate(geometries):
            props = {name: _jsonable(col[i]) for name, col in zip(names, field_data)}
            if assume_kml:
                props = clean_kml_properties(props)
            features.append(
                RawFeature(
                    index=start_index + len(features),
                    layer=str(layer_name),
                    geometry=geom,
                    properties=props,
                    crs=str(crs),
                )
            )
    return features


def _jsonable(value):
    """numpy / NaN / dates -> plain Python values that JSON can store."""
    if isinstance(value, np.generic):
        value = value.item()
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def clean_kml_properties(props: dict) -> dict:
    """Drop KML boilerplate columns and empty values.

    Only used for KML. For shapefiles we keep every column, even empty ones,
    because the column list there was chosen by the file's author.
    """
    return {k: v for k, v in props.items() if k not in KML_NOISE_FIELDS and v is not None}