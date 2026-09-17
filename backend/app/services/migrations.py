"""Minimal, dependency-free schema patcher.

This project has no Alembic migrations wired up — `Base.metadata.create_all`
(called in `app/main.py`'s `lifespan`) only creates *missing tables*; it never
`ALTER TABLE`s an existing one to add a newly-introduced column. That's fine
for a brand-new database (the table is created with every current column from
a clean slate), but it silently leaves a column missing on any database that
already had the table before the column was added to `models.py` — every
INSERT/SELECT referencing that column then fails at runtime.

`ensure_schema_migrations` closes that gap for the `users.is_active` /
`users.deactivated_at` columns added alongside the auth/RBAC overhaul,
without requiring a manual operator step or introducing a full migration
framework: it inspects the live schema and issues a raw `ALTER TABLE ...
ADD COLUMN ...` only for whatever is actually missing.

Safe to call on every startup, and safe to call twice in a row against the
same engine — it always checks column existence via `inspect(engine)` first
rather than relying on `ADD COLUMN IF NOT EXISTS`, since SQLite's
`ALTER TABLE ADD COLUMN` doesn't support that clause the way Postgres does.
"""

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


def ensure_schema_migrations(engine: Engine) -> None:
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        # Fresh database — create_all (called right before this) already
        # created `users` with every current column. Nothing to migrate.
        return

    existing_columns = {col["name"] for col in inspector.get_columns("users")}

    with engine.begin() as conn:
        if "is_active" not in existing_columns:
            conn.execute(
                text("ALTER TABLE users ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT TRUE")
            )
            logger.info("Schema migration: added users.is_active")
        if "deactivated_at" not in existing_columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN deactivated_at TIMESTAMP NULL"))
            logger.info("Schema migration: added users.deactivated_at")
