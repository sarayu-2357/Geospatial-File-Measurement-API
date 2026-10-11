"""The two tables. One UploadedFile has many FeatureRecords."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class FileStatus:
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


def _new_id() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class UploadedFile(Base):
    __tablename__ = "uploaded_files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    filename: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default=FileStatus.PROCESSING)
    crs: Mapped[str | None] = mapped_column(Text, nullable=True)
    feature_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    features: Mapped[list["FeatureRecord"]] = relationship(
        back_populates="file",
        cascade="all, delete-orphan",
        order_by="FeatureRecord.feature_index",
    )


class FeatureRecord(Base):
    __tablename__ = "feature_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_id: Mapped[str] = mapped_column(ForeignKey("uploaded_files.id"), index=True)
    feature_index: Mapped[int] = mapped_column(Integer)
    layer: Mapped[str] = mapped_column(String(255))
    geometry_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    geometry: Mapped[dict | None] = mapped_column(JSON, nullable=True)   # GeoJSON, original CRS
    crs: Mapped[str] = mapped_column(Text)
    properties: Mapped[dict] = mapped_column(JSON)
    measurement: Mapped[dict] = mapped_column(JSON)

    file: Mapped["UploadedFile"] = relationship(back_populates="features")