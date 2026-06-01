"""Isolation Forest edge anomaly detection."""

import logging
import pickle
from collections.abc import Sequence
from pathlib import Path
from typing import Optional

import psutil

from app.config import BASE_DIR, settings

logger = logging.getLogger(__name__)

MODEL_PATH = BASE_DIR / "data" / "anomaly_model.pkl"

_SKLEARN_OK: bool | None = None
_IsolationForest = None


def _load_sklearn() -> bool:
    global _IsolationForest, _SKLEARN_OK
    if not settings.enable_anomaly_model:
        _SKLEARN_OK = False
        return False
    if _SKLEARN_OK is not None:
        return _SKLEARN_OK
    try:
        from sklearn.ensemble import IsolationForest
    except ImportError:
        logger.warning("scikit-learn not installed; anomaly detection disabled")
        _SKLEARN_OK = False
        return False
    _IsolationForest = IsolationForest
    _SKLEARN_OK = True
    return True


def sklearn_available() -> bool:
    return _load_sklearn()


class IsolationForestDetector:
    def __init__(self, model_path: Path | None = None):
        self.model_path = model_path or MODEL_PATH
        self.model = None
        if settings.enable_anomaly_model:
            self._load()

    def _load(self) -> None:
        if not _load_sklearn():
            return
        if self.model_path.is_file():
            try:
                with open(self.model_path, "rb") as f:
                    self.model = pickle.load(f)
                logger.info("Loaded anomaly model from %s", self.model_path)
            except Exception as exc:
                logger.warning("Failed to load anomaly model: %s", exc)
                self.model = None

    def collect_features(self) -> list[float]:
        """CPU%, mem%, disk%, temp°C, network bytes/s (approx)"""
        cpu = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory().percent
        disk = psutil.disk_usage("/").percent
        temp = _read_temp_c()
        net = _net_bytes_per_sec()
        return [float(cpu), float(mem), float(disk), float(temp if temp is not None else 0.0), float(net)]

    def train(self, historical_data: Sequence[Sequence[float]]) -> bool:
        if not _load_sklearn() or _IsolationForest is None:
            return False
        import numpy as np

        rows = np.asarray(historical_data, dtype=float)
        if rows.shape[0] < 100:
            logger.info("Skip train: only %s samples (need 100)", rows.shape[0])
            return False
        self.model = _IsolationForest(contamination=0.1, n_estimators=100, random_state=42)
        self.model.fit(rows)
        self.save_model()
        logger.info("Trained anomaly model on %s samples", rows.shape[0])
        return True

    def predict(self, features: Sequence[float]) -> tuple[bool, float]:
        if self.model is None or not _load_sklearn():
            return False, 0.0
        import numpy as np

        x = np.asarray(features, dtype=float).reshape(1, -1)
        pred = self.model.predict(x)[0]
        score = float(-self.model.decision_function(x)[0])
        is_anomaly = pred == -1
        return is_anomaly, score

    def save_model(self) -> None:
        if self.model is None:
            return
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.model_path, "wb") as f:
            pickle.dump(self.model, f)


def _read_temp_c() -> Optional[float]:
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", encoding="utf-8") as f:
            return round(int(f.read().strip()) / 1000.0, 1)
    except OSError:
        return None


_net_last: tuple[float, float] | None = None


def _net_bytes_per_sec() -> float:
    global _net_last
    counters = psutil.net_io_counters()
    now = counters.bytes_sent + counters.bytes_recv
    import time

    t = time.time()
    if _net_last is None:
        _net_last = (now, t)
        return 0.0
    prev_bytes, prev_t = _net_last
    dt = max(t - prev_t, 0.001)
    rate = (now - prev_bytes) / dt
    _net_last = (now, t)
    return round(rate, 0)


def likely_cause(features: Sequence[float], mean: Sequence[float] | None) -> str:
    labels = ["CPU", "Memory", "Disk", "Temperature", "Network"]
    if mean is None or len(mean) != len(features):
        return "Unusual combined pattern"
    deltas = [abs(float(value) - float(avg)) for value, avg in zip(features, mean)]
    idx = max(range(len(deltas)), key=deltas.__getitem__)
    return f"High {labels[idx]} ({features[idx]:.1f} vs avg {mean[idx]:.1f})"
