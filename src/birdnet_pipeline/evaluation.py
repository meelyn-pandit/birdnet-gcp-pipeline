"""Detection metrics on labeled windows (1 present, 0 absent, -1 excluded)."""
import csv
import math
from pathlib import Path

import numpy as np


def metrics(y, scores, threshold: float) -> dict:
    y, scores = np.asarray(y), np.asarray(scores, dtype=float)
    keep = y >= 0
    y, scores = y[keep], scores[keep]
    pred = scores >= threshold
    tp = int((pred & (y == 1)).sum())
    fp = int((pred & (y == 0)).sum())
    pos = int((y == 1).sum())
    ap = math.nan
    if 0 < pos < len(y):
        from sklearn.metrics import average_precision_score
        ap = float(average_precision_score(y, scores))
    return {"threshold": threshold, "found": tp, "positives": pos, "false_alarms": fp,
            "precision": tp / (tp + fp) if tp + fp else math.nan,
            "recall": tp / pos if pos else math.nan, "average_precision": ap}


def format_row(name: str, m: dict) -> str:
    return (f"  {name:40} found {m['found']:3}/{m['positives']:<3} false alarms {m['false_alarms']:3}   "
            f"precision {m['precision']:4.2f}  recall {m['recall']:4.2f}  AP {m['average_precision']:4.2f}")


def read_split(path) -> dict[str, str]:
    """recording -> split ('train' / 'test') from split.csv."""
    with open(path, newline="") as f:
        return {r["recording"]: r["split"] for r in csv.DictReader(f)}


def find_audio(folder, recording: str) -> Path:
    folder = Path(folder)
    for ext in (".WAV", ".wav", ".flac", ".FLAC"):
        p = folder / f"{recording}{ext}"
        if p.exists():
            return p
    matches = sorted(folder.glob(f"{recording}.*")) or sorted(folder.rglob(f"{recording}.*"))
    if not matches:
        raise FileNotFoundError(f"No audio for {recording} in {folder}")
    return matches[0]
