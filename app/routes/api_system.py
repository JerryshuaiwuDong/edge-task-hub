from fastapi import APIRouter

from app.system_monitor import get_cpu_history, get_services_status, get_snapshot

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/snapshot")
def system_snapshot():
    return get_snapshot()


@router.get("/cpu-history")
def cpu_history():
    return {"points": get_cpu_history()}


@router.get("/services")
def services_status():
    return {"services": get_services_status()}
