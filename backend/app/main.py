from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.database import Base, SessionLocal, engine
from app.routers import (
    admin,
    auth,
    departments,
    notifications,
    projects,
    reports,
    tasks,
    teams,
    time_entries,
    users,
)
from app.services.bootstrap import ensure_bootstrap_admin, ensure_default_dropdown_options
from app.services.migrations import ensure_schema_migrations

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_schema_migrations(engine)
    db = SessionLocal()
    try:
        ensure_bootstrap_admin(db)
        ensure_default_dropdown_options(db)
    finally:
        db.close()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.effective_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(departments.router)
app.include_router(teams.router)
app.include_router(projects.router)
app.include_router(tasks.router)
app.include_router(time_entries.router)
app.include_router(admin.router)
app.include_router(reports.router)
app.include_router(notifications.router)


@app.get("/health")
def health_check():
    return {"status": "ok"}
