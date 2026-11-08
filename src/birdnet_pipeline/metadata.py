"""Build the per-recording metadata table (one row per audio file).

Site ID comes from a folder name in the path (default: the file's parent
folder). The start time is parsed from the filename (AudioMoth / Song Meter
style names such as 20240512_053000.WAV or SITE_20240512_053000.wav) and
converted to UTC using the site's time zone from sites.csv.

rel_path always begins with the site folder (aru01/20240512_053000.WAV),
matching the bucket layout gs://BUCKET/RAW_PREFIX/<site>/... used by
infra/gcp/upload.sh. Sites share timestamp filenames, so this keeps paths
and recording IDs unique.
"""
import csv
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

AUDIO_EXTS = {".wav", ".flac", ".mp3", ".ogg"}
FIELDS = [
    "recording_id", "rel_path", "site_id", "latitude", "longitude", "recorder",
    "start_utc", "birdnet_week", "duration_s", "sample_rate", "channels",
    "format", "size_bytes", "error",
]
DEFAULT_TS_REGEX = r"(\d{8})_(\d{6})"


def birdnet_week(dt: datetime) -> int:
    """BirdNET splits the year into 48 weeks: 4 per month (1-48)."""
    return (dt.month - 1) * 4 + min(4, (dt.day - 1) // 7 + 1)


def load_sites(path) -> dict:
    sites = {}
    if not path:
        return sites
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            sites[row["site_id"].strip()] = row
    return sites


def audio_files(root):
    for p in sorted(Path(root).resolve().rglob("*")):
        if p.is_file() and p.suffix.lower() in AUDIO_EXTS and not p.name.startswith("."):
            yield p


def metadata_row(p: Path, sites: dict, site_level: int = 1, ts_re=None,
                 default_tz: str = "UTC") -> dict:
    import soundfile as sf

    ts_re = ts_re or re.compile(DEFAULT_TS_REGEX)
    # Absolute path, so files sitting directly in root still get a site ID.
    site_dir = p.parents[site_level - 1]
    site_id = site_dir.name
    rel = p.relative_to(site_dir.parent).as_posix()
    row = {k: "" for k in FIELDS}
    row.update(rel_path=rel, site_id=site_id, size_bytes=p.stat().st_size,
               format=p.suffix.lower().lstrip("."),
               recording_id=hashlib.sha1(rel.encode()).hexdigest()[:16])
    errors = []
    site = sites.get(site_id)
    if site:
        row.update(latitude=site.get("latitude", ""), longitude=site.get("longitude", ""),
                   recorder=site.get("recorder", ""))
    tz_name = (site or {}).get("timezone") or default_tz

    m = ts_re.search(p.stem)
    if m:
        try:
            local = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
            utc = local.replace(tzinfo=ZoneInfo(tz_name)).astimezone(timezone.utc)
            row["start_utc"] = utc.strftime("%Y-%m-%d %H:%M:%S UTC")
            row["birdnet_week"] = birdnet_week(local)
        except Exception as e:  # bad date or unknown tz
            errors.append(f"timestamp: {e}")
    else:
        errors.append("timestamp: no match in filename")

    try:
        info = sf.info(str(p))
        row.update(duration_s=round(info.duration, 3), sample_rate=info.samplerate,
                   channels=info.channels)
    except Exception as e:
        errors.append(f"decode: {e}")

    row["error"] = "; ".join(errors)
    return row
