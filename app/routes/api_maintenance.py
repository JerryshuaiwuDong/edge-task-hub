from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.maintenance import build_preview, explain_with_ollama, get_status, run_cleanup

router = APIRouter(prefix="/api/maintenance", tags=["maintenance"])


class CleanupRequest(BaseModel):
    confirm: bool = False


@router.get("/status")
def maintenance_status(db: Session = Depends(get_db)):
    return get_status(db)


@router.get("/preview")
def maintenance_preview(db: Session = Depends(get_db)):
    return build_preview(db)


@router.post("/run")
def maintenance_run(body: CleanupRequest, db: Session = Depends(get_db)):
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Set confirm=true to run project cleanup.")
    try:
        return run_cleanup(db, trigger="manual", confirmed=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/explain")
def maintenance_explain(db: Session = Depends(get_db)):
    return explain_with_ollama(db)
