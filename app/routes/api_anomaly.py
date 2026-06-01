from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import SystemMetric

router = APIRouter(prefix="/api/anomaly", tags=["anomaly"])


@router.get("/stats")
def anomaly_stats(db: Session = Depends(get_db)):
    total = db.query(SystemMetric).count()
    since = datetime.utcnow() - timedelta(hours=24)
    recent = (
        db.query(SystemMetric)
        .filter(SystemMetric.timestamp >= since)
        .order_by(SystemMetric.timestamp.asc())
        .all()
    )
    anomalies_24h = sum(1 for m in recent if m.is_anomaly)
    if not settings.enable_anomaly_model:
        return {
            "enabled": False,
            "sklearn_available": False,
            "model_trained": False,
            "samples_collected": total,
            "anomalies_24h": anomalies_24h,
        }

    from app.ai.anomaly_detector import IsolationForestDetector, sklearn_available

    detector = IsolationForestDetector()
    return {
        "enabled": True,
        "sklearn_available": sklearn_available(),
        "model_trained": detector.model is not None,
        "samples_collected": total,
        "anomalies_24h": anomalies_24h,
    }


@router.get("/series")
def anomaly_series(db: Session = Depends(get_db)):
    since = datetime.utcnow() - timedelta(hours=24)
    rows = (
        db.query(SystemMetric)
        .filter(SystemMetric.timestamp >= since)
        .order_by(SystemMetric.timestamp.asc())
        .all()
    )
    return {
        "points": [
            {
                "ts": r.timestamp.isoformat() + "Z",
                "score": r.anomaly_score or 0,
                "is_anomaly": r.is_anomaly,
                "cpu": r.cpu,
                "mem": r.mem,
                "disk": r.disk,
                "temp": r.temp,
            }
            for r in rows
        ]
    }


@router.get("/events")
def anomaly_events(db: Session = Depends(get_db), limit: int = 30):
    since = datetime.utcnow() - timedelta(days=7)
    rows = (
        db.query(SystemMetric)
        .filter(SystemMetric.is_anomaly.is_(True))
        .filter(SystemMetric.timestamp >= since)
        .order_by(SystemMetric.timestamp.desc())
        .limit(limit)
        .all()
    )
    hist = db.query(SystemMetric).filter(SystemMetric.timestamp >= since).all()
    mean = _feature_mean([[r.cpu, r.mem, r.disk, r.temp or 0.0, r.network] for r in hist])
    if settings.enable_anomaly_model:
        from app.ai.anomaly_detector import likely_cause
    else:
        likely_cause = None

    events = []
    for r in rows:
        feats = [r.cpu, r.mem, r.disk, r.temp or 0.0, r.network]
        events.append(
            {
                "timestamp": r.timestamp.isoformat() + "Z",
                "score": r.anomaly_score,
                "cpu": r.cpu,
                "mem": r.mem,
                "disk": r.disk,
                "temp": r.temp,
                "network": r.network,
                "likely_cause": likely_cause(feats, mean) if likely_cause and mean is not None else "—",
            }
        )
    return {"events": events}


@router.post("/train")
def train_now():
    if not settings.enable_anomaly_model:
        return {"ok": False, "message": "Anomaly model is disabled by ENABLE_ANOMALY_MODEL=false."}
    from app.anomaly_jobs import manual_train

    return manual_train()


def _feature_mean(rows: list[list[float]]) -> list[float] | None:
    if not rows:
        return None
    width = len(rows[0])
    return [sum(float(row[i]) for row in rows) / len(rows) for i in range(width)]
