"""Database plumbing: engine, session factory, and the FastAPI dependency."""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app import config


class Base(DeclarativeBase):
    """All tables inherit from this."""


# check_same_thread=False: FastAPI runs sync endpoints in a thread pool, and
# SQLite by default refuses to be used from a different thread than the one
# that opened it.
engine = create_engine(config.DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    """Create tables if they don't exist yet."""
    from app import models  # noqa: F401  (importing registers the tables on Base)
    Base.metadata.create_all(engine)


def get_db():
    """FastAPI dependency: one session per request, always closed afterwards."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()