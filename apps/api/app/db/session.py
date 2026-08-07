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


def create_session() -> Session:
    """Return a production session bound to the configured database engine.

    CLI processes and workers do not run through FastAPI dependency injection, so
    they must bind SessionLocal explicitly just like request-scoped get_db().
    """
    return SessionLocal(bind=get_engine())


def get_db() -> Generator[Session, None, None]:
    db = create_session()
    try:
        yield db
    finally:
        db.close()
