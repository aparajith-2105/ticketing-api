from sqlalchemy import create_engine, event as sa_event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

is_sqlite = settings.database_url.startswith("sqlite")
connect_args = {"check_same_thread": False, "timeout": 30} if is_sqlite else {}

engine = create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)

if is_sqlite:
    @sa_event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()