"""Creates the FastAPI app, configures logging, and turns our exceptions into JSON."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app import config
from app.api import files
from app.db import init_db
from app.errors import GeoAPIError

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs once at startup (before yield) and once at shutdown (after)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    init_db()
    logger.info("Geo Measurement API started")
    yield


app = FastAPI(
    title="Geospatial File Measurement API",
    description="Upload a KML or zipped Shapefile and get per-feature area/length measurements.",
    lifespan=lifespan,
)


@app.exception_handler(GeoAPIError)
async def geo_error_handler(request: Request, exc: GeoAPIError):
    """One place that converts any GeoAPIError into a consistent JSON error."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.message, "file_id": exc.file_id},
    )


app.include_router(files.router)