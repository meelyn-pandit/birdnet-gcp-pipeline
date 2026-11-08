"""Single-species classifiers on embeddings, and saving/loading them."""
import time
from pathlib import Path

import joblib


def make_classifier(C: float = 0.01):
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    return make_pipeline(StandardScaler(),
                         LogisticRegression(C=C, class_weight="balanced", max_iter=5000))


def save_bundle(path, model, **meta) -> Path:
    """Save a model with the metadata needed to use and audit it."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "created": time.strftime("%Y-%m-%d %H:%M"), **meta}, path)
    return path


def load_bundle(path) -> dict:
    return joblib.load(path)
