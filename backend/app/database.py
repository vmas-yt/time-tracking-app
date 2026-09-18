from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import get_settings

settings = get_settings()

is_sqlite = settings.database_url.startswith("sqlite")
connect_args = {"check_same_thread": False} if is_sqlite else {}
if settings.db_schema and not is_sqlite:
    # Scope this engine's connections into a dedicated Postgres schema via
    # `search_path`, same mechanism already proven in
    # tests/test_migration_old_schema_with_real_data.py. Standard
    # psycopg2 pattern: libpq accepts `-c NAME=VALUE` options and applies
    # them as `SET NAME = VALUE` on each new connection.
    connect_args = {**connect_args, "options": f"-c search_path={settings.db_schema}"}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
