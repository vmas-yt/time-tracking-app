from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import TimeEntry, User, UserRole
from app.schemas import ReminderCandidate

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("/reminders", response_model=list[ReminderCandidate])
def reminder_candidates(
    days: int = Query(1, ge=1, le=30, description="Flag anyone with no logged time in this many days"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Employees who haven't logged time recently — the data behind the
    compliance reminder to the employee and their line manager (there is
    no approval step, so this is the main compliance signal per the PRD).

    This endpoint only computes *who* needs a nudge; wiring it up to an
    actual delivery channel (email/Slack) is a follow-up that needs
    outbound-notification infrastructure this scaffold doesn't have.
    """
    if current_user.role == UserRole.ADMIN:
        scope = db.query(User)
    elif current_user.role == UserRole.MANAGER:
        scope = db.query(User).filter(User.manager_id == current_user.id)
    else:
        scope = db.query(User).filter(User.id == current_user.id)

    users = scope.all()
    last_logged = dict(
        db.query(TimeEntry.user_id, func.max(TimeEntry.started_at)).group_by(TimeEntry.user_id).all()
    )
    cutoff = datetime.utcnow() - timedelta(days=days)

    candidates = []
    for user in users:
        last = last_logged.get(user.id)
        if last is None or last < cutoff:
            candidates.append(
                ReminderCandidate(
                    user_id=user.id,
                    full_name=user.full_name,
                    email=user.email,
                    manager_id=user.manager_id,
                    last_logged_at=last,
                )
            )
    return candidates
