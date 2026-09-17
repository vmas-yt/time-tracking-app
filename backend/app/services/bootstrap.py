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
from app.models import DropdownOption, DropdownOptionScope, User, UserRole

logger = logging.getLogger(__name__)

# Source list mirrored from the PRD's fixed category list / the frontend's
# TASK_CATEGORIES display strings (frontend/src/lib/types.ts), per
# docs/design/custom-fields-admin-design.md §2.4.
DEFAULT_TASK_CATEGORIES: list[tuple[str, str]] = [
    ("production_issue", "Production Issue"),
    ("urgent_request", "Urgent Request"),
    ("meeting", "Meeting"),
    ("support_ticket", "Support Ticket"),
    ("cyber_security_request", "Cyber Security Request"),
    ("platform_support", "Platform Support"),
    ("infrastructure", "Infrastructure"),
    ("other", "Others"),
]

DEFAULT_TASK_PRIORITIES: list[tuple[str, str]] = [
    ("normal", "Normal"),
    ("expedite", "Expedite"),
]


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


def ensure_default_dropdown_options(db: Session) -> None:
    """Seed the built-in task_category/task_priority DropdownOption rows on
    cold start (§2.4). Idempotent: only ever seeds a scope that currently has
    zero rows — never re-seeds a live table, mirroring
    `ensure_bootstrap_admin`'s "only touches empty" convention.
    """
    has_categories = (
        db.query(DropdownOption).filter(DropdownOption.scope == DropdownOptionScope.TASK_CATEGORY).first()
        is not None
    )
    if not has_categories:
        for position, (value, label) in enumerate(DEFAULT_TASK_CATEGORIES):
            db.add(
                DropdownOption(
                    scope=DropdownOptionScope.TASK_CATEGORY,
                    custom_field_id=None,
                    value=value,
                    label=label,
                    is_builtin=True,
                    is_active=True,
                    position=position,
                )
            )
        db.commit()
        logger.info("Seeded default task_category dropdown options")

    has_priorities = (
        db.query(DropdownOption).filter(DropdownOption.scope == DropdownOptionScope.TASK_PRIORITY).first()
        is not None
    )
    if not has_priorities:
        for position, (value, label) in enumerate(DEFAULT_TASK_PRIORITIES):
            db.add(
                DropdownOption(
                    scope=DropdownOptionScope.TASK_PRIORITY,
                    custom_field_id=None,
                    value=value,
                    label=label,
                    is_builtin=True,
                    is_active=True,
                    position=position,
                )
            )
        db.commit()
        logger.info("Seeded default task_priority dropdown options")
