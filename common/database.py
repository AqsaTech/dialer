from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from common.config import get_settings


class Base(DeclarativeBase):
    pass


_url = get_settings().database_url
_connect_args = {"check_same_thread": False, "timeout": 30} if _url.startswith("sqlite") else {}

engine = create_engine(
    _url,
    pool_pre_ping=True,
    pool_recycle=3600,
    echo=False,
    connect_args=_connect_args,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
