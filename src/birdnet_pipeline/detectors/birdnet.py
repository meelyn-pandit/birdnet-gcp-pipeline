"""Read BirdNET-Analyzer output (Raven selection tables)."""
import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..annotations import overlap, species_key, stem


@dataclass(frozen=True)
class Detection:
    start: float
    end: float
    common_name: str
    confidence: float


def selection_tables(folder) -> list[Path]:
    return sorted(Path(folder).glob("*.selection.table.txt"))


def table_path(folder, recording: str) -> Path:
    return Path(folder) / f"{recording}.BirdNET.selection.table.txt"


def recording_of(table: Path) -> str:
    """20210524_053000.BirdNET.selection.table.txt -> 20210524_053000."""
    return stem(table.name)


def read_detections(path, include_nocall: bool = False) -> list[Detection]:
    out = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            name = (r.get("Common Name") or "").strip()
            if not name or (name.lower() == "nocall" and not include_nocall):
                continue
            out.append(Detection(float(r["Begin Time (s)"]), float(r["End Time (s)"]),
                                 name, float(r.get("Confidence") or 0)))
    return out


def window_scores(detections, species: str, windows) -> np.ndarray:
    """Max confidence for species over detections covering >= half of each window."""
    key = species_key(species)
    out = np.zeros(len(windows))
    for d in detections:
        if species_key(d.common_name) != key:
            continue
        for k, (w0, w1) in enumerate(windows):
            if overlap(d.start, d.end, w0, w1) >= (w1 - w0) / 2:
                out[k] = max(out[k], d.confidence)
    return out
