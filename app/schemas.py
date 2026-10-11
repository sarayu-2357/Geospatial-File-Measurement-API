"""Pydantic models: the exact JSON shape the API returns."""
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, field_validator
from pydantic import BaseModel, ConfigDict


class FileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)   # lets Pydantic read SQLAlchemy objects

    id: str
    filename: str
    status: str
    crs: str | None
    feature_count: int
    error_message: str | None
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _assume_utc(cls, value: datetime) -> datetime:
        """SQLite drops timezone info, so a value read back is naive. We always store UTC."""
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class FeatureOut(BaseModel):
    feature_id: int
    layer: str
    geometry_type: str | None
    crs: str
    properties: dict
    geometry: dict | None
    measurement: dict


class MeasurementsOut(BaseModel):
    file_id: str
    filename: str
    status: str
    crs: str | None
    feature_count: int
    summary: dict
    features: list[FeatureOut]