import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import BASE_DIR
from app.database import Base, engine
from app.migrations import run_migrations
from app.routes import (
    api_anomaly,
    api_external,
    api_feishu,
    api_maintenance,
    api_model,
    api_system,
    api_tasks,
    pages,
)
from app.seed import seed_demo_task_if_empty
from app.scheduler import shutdown_scheduler, start_scheduler
from app.system_monitor import sample_cpu_ring

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    run_migrations()
    seed_demo_task_if_empty()
    start_scheduler()
    sample_cpu_ring()
    logger.info("Edge Task Hub started")
    yield
    shutdown_scheduler()
    logger.info("Edge Task Hub stopped")


app = FastAPI(
    title="Edge Task Hub",
    description="Configure scheduled edge tasks with Lark/Feishu notifications.",
    version="1.0.0",
    lifespan=lifespan,
)

static_dir = BASE_DIR / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

app.include_router(api_tasks.router)
app.include_router(api_anomaly.router)
app.include_router(api_external.router)
app.include_router(api_feishu.router)
app.include_router(api_model.router)
app.include_router(api_system.router)
app.include_router(api_maintenance.router)
app.include_router(pages.router)
