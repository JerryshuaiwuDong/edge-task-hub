"""Background anomaly-detection sampling."""

import logging
from datetime import datetime, timedelta

from app.config import settings
from app.database import SessionLocal
from app.models import SystemMetric

logger = logging.getLogger(__name__)

_detector = None


def _get_detector():
    global _detector
    if _detector is None:
        from app.ai.anomaly_detector import IsolationForestDetector

        _detector = IsolationForestDetector()
    return _detector


def anomaly_enabled() -> bool:
    if not settings.enable_anomaly_model:
        return False
    from app.ai.anomaly_detector import sklearn_available

    return sklearn_available()


def collect_and_score_metric():
    if not anomaly_enabled():
        return
    detector = _get_detector()
    features = detector.collect_features()
    db = SessionLocal()
    try:
        metric = SystemMetric(
            timestamp=datetime.utcnow(),
            cpu=float(features[0]),
            mem=float(features[1]),
            disk=float(features[2]),
            temp=float(features[3]) if features[3] else None,
            network=float(features[4]),
        )
        if detector.model is not None:
            is_anom, score = detector.predict(features)
            metric.is_anomaly = is_anom
            metric.anomaly_score = score
        db.add(metric)
        db.commit()
        try:
            from app.maintenance import maybe_auto_cleanup

            result = maybe_auto_cleanup(metric)
            if result.get("ran"):
                logger.info("Auto maintenance cleanup ran: %s", result.get("reasons"))
        except Exception as exc:
            logger.warning("Auto maintenance cleanup skipped: %s", exc)
    finally:
        db.close()


def daily_retrain():
    if not anomaly_enabled():
        return
    detector = _get_detector()
    db = SessionLocal()
    try:
        since = datetime.utcnow() - timedelta(days=7)
        rows = (
            db.query(SystemMetric)
            .filter(SystemMetric.timestamp >= since)
            .order_by(SystemMetric.timestamp.asc())
            .all()
        )
        if len(rows) < 100:
            logger.info("Anomaly retrain skipped: %s samples", len(rows))
            return
        data = [[r.cpu, r.mem, r.disk, r.temp or 0.0, r.network] for r in rows]
        detector.train(data)
    finally:
        db.close()


def manual_train() -> dict:
    if not anomaly_enabled():
        return {"ok": False, "message": "scikit-learn is not installed."}
    daily_retrain()
    trained = _get_detector().model is not None
    return {
        "ok": trained,
        "message": "Model trained successfully." if trained else "Not enough samples (need 100+ in last 7 days).",
    }
