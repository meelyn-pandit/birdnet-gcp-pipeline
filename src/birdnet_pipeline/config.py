"""Per-species settings from configs/species.toml."""
import tomllib
from pathlib import Path

from . import paths
from .annotations import species_key

DEFAULTS = {"perch_cutoffs": [8, 7, 6], "classifier_C": 0.01, "classifier_threshold": 0.5}


def species_settings(common_name: str, path=None) -> dict:
    """Settings for a species (by common name), merged over DEFAULTS; {} keys if not configured."""
    path = Path(path or paths.SPECIES_TOML)
    settings = dict(DEFAULTS, common=common_name)
    if path.exists():
        for entry in tomllib.loads(path.read_text()).values():
            if species_key(entry.get("common", "")) == species_key(common_name):
                settings.update(entry)
                break
    return settings


def slug(common_name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in common_name.lower()).strip("_")
