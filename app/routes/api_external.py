from fastapi import APIRouter

from app.external_sources.registry import list_all_external_tasks, summarize_external

router = APIRouter(prefix="/api", tags=["external"])


@router.get("/external-tasks")
def get_external_tasks():
    tasks, warnings = list_all_external_tasks()
    return {
        "tasks": [t.model_dump(mode="json") for t in tasks],
        "warnings": [w.model_dump() for w in warnings],
        "summary": summarize_external(tasks),
    }
