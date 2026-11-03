#!/usr/bin/env python3
"""Walk a recordings folder and build metadata.csv, one row per audio file.

Site ID comes from a folder name in the path (default: the file's parent
folder). The start time is parsed from the filename (default pattern matches
AudioMoth / Song Meter style names such as 20240512_053000.WAV or
SITE_20240512_053000.wav) and converted to UTC using the site's time zone
from sites.csv.

rel_path always begins with the site folder (e.g. aru01/20240512_053000.WAV),
matching the bucket layout gs://BUCKET/RAW_PREFIX/<site>/... used by upload.sh.

Example:
    python scripts/build_metadata.py /Volumes/Field/recordings \
        --sites config/sites.csv -o metadata.csv
"""
import argparse
import csv
import hashlib
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import soundfile as sf

AUDIO_EXTS = {".wav", ".flac", ".mp3", ".ogg"}
FIELDS = [
    "recording_id", "rel_path", "site_id", "latitude", "longitude", "recorder",
    "start_utc", "birdnet_week", "duration_s", "sample_rate", "channels",
    "format", "size_bytes", "error",
]


def birdnet_week(dt: datetime) -> int:
    """BirdNET splits the year into 48 weeks: 4 per month (1-48)."""
    return (dt.month - 1) * 4 + min(4, (dt.day - 1) // 7 + 1)


def load_sites(path):
    sites = {}
    if not path:
        return sites
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            sites[row["site_id"].strip()] = row
    return sites


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", type=Path, help="Folder containing the recordings")
    ap.add_argument("--sites", help="sites.csv with site_id, latitude, longitude, recorder, timezone")
    ap.add_argument("-o", "--output", default="metadata.csv")
    ap.add_argument("--site-level", type=int, default=1,
                    help="Which parent folder holds the site ID: 1 = immediate parent (default), "
                         "2 = grandparent, and so on")
    ap.add_argument("--ts-regex", default=r"(\d{8})_(\d{6})",
                    help="Regex with two groups: YYYYMMDD and HHMMSS")
    ap.add_argument("--default-tz", default="UTC",
                    help="Time zone for sites missing from sites.csv (default UTC)")
    args = ap.parse_args()

    root = args.root.resolve()
    sites = load_sites(args.sites)
    ts_re = re.compile(args.ts_regex)
    unknown_sites = set()
    n = n_err = 0

    with open(args.output, "w", newline="") as out:
        w = csv.DictWriter(out, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        for p in sorted(root.rglob("*")):
            if not p.is_file() or p.suffix.lower() not in AUDIO_EXTS or p.name.startswith("."):
                continue
            # Use the absolute path so files sitting directly in root still
            # get a site ID (root's own folder name, e.g. .../aru01).
            site_dir = p.parents[args.site_level - 1]
            site_id = site_dir.name
            # rel_path always starts at the site folder (aru01/20210523_050000.WAV),
            # whether root is the site folder or a folder above it. Sites share
            # timestamp filenames, so this keeps paths and IDs unique.
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
            elif sites:
                unknown_sites.add(site_id)
            tz_name = (site or {}).get("timezone") or args.default_tz

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
            n += 1
            n_err += bool(errors)
            w.writerow(row)

    print(f"Wrote {n} rows to {args.output} ({n_err} with errors)")
    if unknown_sites:
        print(f"Sites not found in {args.sites}: {', '.join(sorted(unknown_sites))}", file=sys.stderr)


if __name__ == "__main__":
    main()
