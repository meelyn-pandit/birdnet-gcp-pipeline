"""Annotation formats and the rules that map annotations onto analysis windows.

This module is the single source of truth for how a label is interpreted.
Labeling, training and evaluation all use it, so they can never disagree
about what a label means.

Label text conventions (Audacity labels):
    Indigo Bunting            positive
    Indigo Bunting 0.43       positive (a leftover BirdNET score is ignored)
    - Indigo Bunting          negative (also "neg ..." / "not ...")
    ? Indigo Bunting 0.43     unsure / unreviewed: never a positive, and
                              excluded from negatives
"""
import csv
import re
from dataclasses import dataclass
from pathlib import Path

POS, NEG, UNSURE = "pos", "neg", "unsure"
TYPE_WORDS = {"pos": POS, "positive": POS, "neg": NEG, "negative": NEG}

_NEG_PREFIX = re.compile(r"^(?:-|neg\b|not\b)\s*", re.IGNORECASE)
_UNSURE_PREFIX = re.compile(r"^\?\s*")
_TRAILING_SCORE = re.compile(r"\s+[01](?:\.\d+)?$")


def stem(name) -> str:
    """Recording name without folders or extensions: a/b/20210524_053000.WAV -> 20210524_053000."""
    return Path(str(name)).name.split(".")[0]


def overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    """Length of the overlap of two intervals (negative if they do not overlap)."""
    return min(a1, b1) - max(a0, b0)


def parse_label_text(text: str) -> tuple[str, str]:
    """Return (label, kind) for Audacity label text; kind is pos, neg or unsure."""
    t = text.strip()
    if not t:
        return "", UNSURE
    kind = POS
    if _UNSURE_PREFIX.match(t):
        kind, t = UNSURE, _UNSURE_PREFIX.sub("", t)
    elif _NEG_PREFIX.match(t):
        kind, t = NEG, _NEG_PREFIX.sub("", t)
    return _TRAILING_SCORE.sub("", t.strip()).strip(), kind


def species_key(label: str) -> str:
    """Case-insensitive key for comparing species names."""
    return label.strip().lower()


@dataclass(frozen=True)
class Annotation:
    recording: str      # recording stem
    start: float
    end: float
    label: str
    kind: str           # POS, NEG or UNSURE
    provenance: str = ""
    where: str = ""     # file:line, for messages


def read_audacity(path, provenance: str = "") -> list[Annotation]:
    """Read an Audacity label file; the recording is named by the file (labels/<rec>.txt)."""
    path = Path(path)
    out = []
    for i, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip() or line.startswith("\\"):      # "\" lines hold spectral selections
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            raise ValueError(f"{path}:{i}: expected start<TAB>end<TAB>label, got {line!r}")
        label, kind = parse_label_text(parts[2])
        out.append(Annotation(stem(path.name), float(parts[0]), float(parts[1]), label, kind,
                              provenance, f"{path.name}:{i}"))
    return out


def read_review_csv(path, provenance: str = "") -> list[Annotation]:
    """Review sheet CSV: file,start_s,end_s,label,type[,provenance]; blank type = unsure."""
    path = Path(path)
    out = []
    with open(path, newline="") as f:
        for i, row in enumerate(csv.DictReader(f), start=2):
            row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
            typ = row.get("type", "").lower()
            if typ and typ not in TYPE_WORDS:
                raise ValueError(f"{path}:{i}: unknown type {typ!r} (use pos or neg)")
            if not (row.get("file") and row.get("label")):
                raise ValueError(f"{path}:{i}: missing file or label")
            out.append(Annotation(stem(row["file"]), float(row["start_s"]), float(row["end_s"]),
                                  row["label"], TYPE_WORDS.get(typ, UNSURE),
                                  row.get("provenance") or provenance, f"{path.name}:{i}"))
    return out


def read_raven(path, label_col: str = "Common Name", provenance: str = "") -> list[Annotation]:
    """Raven selection table; every row except 'nocall' is a positive."""
    path = Path(path)
    out = []
    with open(path, newline="") as f:
        for i, row in enumerate(csv.DictReader(f, delimiter="\t"), start=2):
            label = (row.get(label_col) or "").strip()
            if not label or label.lower() == "nocall":
                continue
            rec = row.get("Begin Path") or row.get("Begin File") or path.name
            out.append(Annotation(stem(rec), float(row["Begin Time (s)"]), float(row["End Time (s)"]),
                                  label, POS, provenance, f"{path.name}:{i}"))
    return out


def detect_format(path) -> str:
    path = Path(path)
    if path.suffix.lower() == ".csv":
        return "csv"
    with open(path) as f:
        return "raven" if f.readline().startswith("Selection\t") else "audacity"


def read_annotations(path, provenance: str = "", label_col: str = "Common Name") -> list[Annotation]:
    """Read any supported annotation file (format detected automatically)."""
    fmt = detect_format(path)
    if fmt == "csv":
        return read_review_csv(path, provenance)
    if fmt == "raven":
        return read_raven(path, label_col, provenance)
    return read_audacity(path, provenance)


def window_hits(start: float, end: float, windows, min_overlap: float = 0.5) -> list[int]:
    """Indices of windows [(w0, w1), ...] an annotation counts for.

    Point labels (end <= start) hit the window containing the point. Calls
    shorter than 2 * min_overlap only need to overlap by half their length,
    so a short note straddling a window boundary still counts.
    """
    if end <= start:
        return [k for k, (w0, w1) in enumerate(windows) if w0 <= start < w1]
    need = min(min_overlap, 0.5 * (end - start))
    return [k for k, (w0, w1) in enumerate(windows) if overlap(start, end, w0, w1) >= need]


def grid_windows(n: int, win: float = 3.0) -> list[tuple[float, float]]:
    return [(k * win, (k + 1) * win) for k in range(n)]


def ground_truth(annotations, species: str, windows, min_overlap: float = 0.5):
    """Per window: 1 = species present, 0 = absent, -1 = uncertain (excluded).

    Assumes every instance of the species was labeled in this recording.
    Negative labels mean absent; a positive anywhere in a window wins over
    a negative or unsure label in the same window.
    """
    import numpy as np

    key = species_key(species)
    y = np.zeros(len(windows), dtype=int)
    unsure = np.zeros(len(windows), dtype=bool)
    for a in annotations:
        if species_key(a.label) != key or a.kind == NEG:
            continue
        for k in window_hits(a.start, a.end, windows, min_overlap):
            if a.kind == POS:
                y[k] = 1
            else:
                unsure[k] = True
    y[(y == 0) & unsure] = -1
    return y


def audacity_line(start: float, end: float, label: str) -> str:
    return f"{start:.6f}\t{end:.6f}\t{label}\n"
