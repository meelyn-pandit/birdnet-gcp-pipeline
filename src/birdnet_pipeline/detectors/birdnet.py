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


@dataclass(frozen=True)
class FileDetection:
    recording: str
    start: float
    end: float
    scientific: str
    common: str
    confidence: float


def run_analyzer(audio_dir, out_dir, lat: float, lon: float, week: int,
                 min_conf: float = 0.1, overlap: float = 0.0, threads: int = 4) -> list[FileDetection]:
    """Run BirdNET-Analyzer on every file in audio_dir with one location/week; parse its CSVs.

    Runs as a subprocess so each call starts from a clean BirdNET configuration.
    """
    import subprocess
    import sys

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "birdnet_analyzer.analyze", str(audio_dir), "-o", str(out_dir),
           "--lat", str(lat), "--lon", str(lon), "--week", str(week),
           "--min_conf", str(min_conf), "--overlap", str(overlap),
           "--rtype", "csv", "--threads", str(threads)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"BirdNET failed ({res.returncode}): {res.stderr[-2000:]}")
    dets = []
    for csv_path in sorted(out_dir.glob("*.BirdNET.results.csv")):
        with open(csv_path, newline="") as f:
            for r in csv.DictReader(f):
                dets.append(FileDetection(stem(r.get("File") or csv_path.name), float(r["Start (s)"]),
                                          float(r["End (s)"]), r["Scientific name"], r["Common name"],
                                          float(r["Confidence"])))
    return dets


def species_list(lat: float, lon: float, week: int = -1, threshold: float = 0.03) -> list[tuple[str, str]]:
    """(scientific, common) birds BirdNET's location model expects at lat/lon in week (-1 = year-round)."""
    from birdnet_analyzer import config as cfg
    from birdnet_analyzer import utils
    from birdnet_analyzer.species.utils import get_species_list

    # Same configuration BirdNET's own species command sets up before predicting.
    utils.ensure_model_exists()
    cfg.MODEL_PATH, cfg.LABELS_FILE = cfg.BIRDNET_MODEL_PATH, cfg.BIRDNET_LABELS_FILE
    cfg.SAMPLE_RATE, cfg.SIG_LENGTH = cfg.BIRDNET_SAMPLE_RATE, cfg.BIRDNET_SIG_LENGTH
    cfg.LABELS = utils.read_lines(cfg.LABELS_FILE)
    return [tuple(s.split("_", 1)) for s in get_species_list(lat, lon, week, threshold)]


def label_names() -> dict[str, str]:
    """scientific -> common name for every BirdNET class (used to name Perch classes)."""
    from birdnet_analyzer import config as bn_cfg

    out = {}
    for line in Path(bn_cfg.BIRDNET_LABELS_FILE).read_text().splitlines():
        if "_" in line:
            sci, common = line.split("_", 1)
            out[sci] = common
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
