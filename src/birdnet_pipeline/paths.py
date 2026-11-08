"""Default locations of data, configs, models and reports.

Everything is relative to the project root: the nearest folder above the
current directory that contains pyproject.toml (override with the
BGP_ROOT environment variable). Every CLI also accepts explicit paths, so
these are only defaults. See data/README.md for what lives where.
"""
import os
from pathlib import Path


def project_root() -> Path:
    env = os.environ.get("BGP_ROOT")
    if env:
        return Path(env).resolve()
    here = Path.cwd().resolve()
    for d in (here, *here.parents):
        if (d / "pyproject.toml").exists() and (d / "src" / "birdnet_pipeline").is_dir():
            return d
    return here


ROOT = project_root()

CONFIGS = ROOT / "configs"
SITES_CSV = CONFIGS / "sites.csv"
SPECIES_TOML = CONFIGS / "species.toml"

DATA = ROOT / "data"
RAW = DATA / "raw"
RAW_SAMPLE = RAW / "sample"                         # local recordings used for development
ANNOTATIONS = DATA / "annotations"
LABELS = ANNOTATIONS / "labels"                     # Audacity label files, one per recording
REVIEW_CSV = ANNOTATIONS / "review.csv"
INTERIM = DATA / "interim"
BIRDNET_OUT = INTERIM / "birdnet"                   # BirdNET selection tables
PERCH_CACHE = INTERIM / "perch_cache"               # cached Perch logits/embeddings
PROCESSED = DATA / "processed"
METADATA_CSV = PROCESSED / "metadata.csv"
EMBEDDINGS_DB = PROCESSED / "embeddings_db"         # Perch Hoplite DB of BirdNET embeddings
SPLITS = DATA / "splits"
SPLIT_CSV = SPLITS / "split.csv"

MODELS = ROOT / "models"
REPORTS = ROOT / "reports"
