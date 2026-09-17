"""One-time cold-start admin seed.

`POST /auth/register` has been removed and only an admin can create accounts
(`POST /users`) from now on. That means a brand-new deployment, with an
empty `users` table, has no way to ever log in through the API unless
something seeds the very first admin account. `ensure_bootstrap_admin` is
that seed: it only ever fires against an empty `users` table (never a
"reset"/"ensure an admin always exists" routine), and only if the operator
has configured `BOOTSTRAP_ADMIN_EMAIL`/`BOOTSTRAP_ADMIN_PASSWORD`.
"""

import logging

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.models import User, UserRole

logger = logging.getLogger(__name__)


def ensure_bootstrap_admin(db: Session) -> None:
    if db.query(User).count() > 0:
        return

    settings = get_settings()
    if settings.bootstrap_admin_email and settings.bootstrap_admin_password:
        admin = User(
            email=settings.bootstrap_admin_email,
            full_name=settings.bootstrap_admin_name,
            hashed_password=hash_password(settings.bootstrap_admin_password),
            role=UserRole.ADMIN,
            is_active=True,
        )
        db.add(admin)
        db.commit()
        logger.info("Bootstrap admin created: %s", settings.bootstrap_admin_email)
    else:
        logger.warning(
            "No users exist and BOOTSTRAP_ADMIN_EMAIL/BOOTSTRAP_ADMIN_PASSWORD are not "
            "set — no one can log in. Set both and restart the service."
        )
