import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import Base, SessionLocal, engine
from .routers import auth, meetings, reports, tasks, teams
from .services.notifications import run_daily_reminders
from .timeutil import KST

logging.basicConfig(level=logging.INFO)


def _reminder_job():
    with SessionLocal() as db:
        n = run_daily_reminders(db)
        logging.getLogger("adoz").info("daily reminders sent: %s", n)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)  # 운영에서는 Alembic 마이그레이션 권장
    scheduler = None
    if settings.scheduler_enabled:
        from apscheduler.schedulers.background import BackgroundScheduler

        scheduler = BackgroundScheduler(timezone=KST)
        scheduler.add_job(_reminder_job, "cron", hour=settings.reminder_hour, minute=0)
        scheduler.start()
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(title="ADOZ API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
                   expose_headers=["Content-Disposition"])  # 배포 시 도메인 제한
for r in (auth.router, teams.router, meetings.router, tasks.router, reports.router):
    app.include_router(r)


@app.get("/health")
def health():
    return {"status": "ok"}
