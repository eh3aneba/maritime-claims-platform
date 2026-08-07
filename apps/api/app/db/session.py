from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()


@lru_cache
def get_engine() -> Engine:
    """Create the production engine lazily.

    Lazy creation keeps application imports/test dependency overrides independent from
    the PostgreSQL DBAPI driver while production requests still use the configured engine.
    """
    return create_engine(settings.database_url, pool_pre_ping=True)


SessionLocal = sessionmaker(class_=Session, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal(bind=get_engine())
    try:
        yield db
    finally:
        db.close()
