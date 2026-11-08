"""Walk a recordings folder and build the metadata table, one row per audio file.

See birdnet_pipeline.metadata for how site IDs, rel_path and UTC start
times are derived.

Example:
    bgp-build-metadata /media/.../lwma_audio_files/aru01
    bgp-build-metadata /Volumes/Field/recordings --sites configs/sites.csv -o data/processed/metadata.csv
"""
import argparse
import csv
import re
import sys
from pathlib import Path

from .. import paths
from ..metadata import DEFAULT_TS_REGEX, FIELDS, audio_files, load_sites, metadata_row


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", type=Path, help="Folder containing the recordings")
    ap.add_argument("--sites", default=str(paths.SITES_CSV),
                    help="sites.csv with site_id, latitude, longitude, recorder, timezone "
                         "(default: configs/sites.csv)")
    ap.add_argument("-o", "--output", type=Path, default=paths.METADATA_CSV)
    ap.add_argument("--site-level", type=int, default=1,
                    help="Which parent folder holds the site ID: 1 = immediate parent (default)")
    ap.add_argument("--ts-regex", default=DEFAULT_TS_REGEX,
                    help="Regex with two groups: YYYYMMDD and HHMMSS")
    ap.add_argument("--default-tz", default="UTC",
                    help="Time zone for sites missing from sites.csv (default UTC)")
    args = ap.parse_args(argv)

    sites = load_sites(args.sites if Path(args.sites).exists() else None)
    ts_re = re.compile(args.ts_regex)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    unknown, n, n_err = set(), 0, 0
    with open(args.output, "w", newline="") as out:
        w = csv.DictWriter(out, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        for p in audio_files(args.root):
            row = metadata_row(p, sites, args.site_level, ts_re, args.default_tz)
            if sites and row["site_id"] not in sites:
                unknown.add(row["site_id"])
            n += 1
            n_err += bool(row["error"])
            w.writerow(row)
    print(f"Wrote {n} rows to {args.output} ({n_err} with errors)")
    if unknown:
        print(f"Sites not found in {args.sites}: {', '.join(sorted(unknown))}", file=sys.stderr)


if __name__ == "__main__":
    main()
