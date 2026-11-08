"""Copy a small stratified sample (N files per site) for local testing.

Example:
    bgp-pick-sample /media/.../lwma_audio_files/aru01 --per-site 20
"""
import argparse
import csv
import random
import shutil
from collections import defaultdict
from pathlib import Path

from .. import paths


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", type=Path,
                    help="Folder passed to bgp-build-metadata (a site folder or the folder above it)")
    ap.add_argument("--metadata", type=Path, default=paths.METADATA_CSV)
    ap.add_argument("--dest", type=Path, default=paths.RAW_SAMPLE)
    ap.add_argument("--per-site", type=int, default=3)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args(argv)

    by_site = defaultdict(list)
    with open(args.metadata, newline="") as f:
        for row in csv.DictReader(f):
            if not row["error"]:
                by_site[row["site_id"]].append(row["rel_path"])

    rng = random.Random(args.seed)
    count = 0
    for site, rels in sorted(by_site.items()):
        for rel in rng.sample(rels, min(args.per_site, len(rels))):
            # rel_path starts with the site folder; root may be that folder or its parent.
            src = args.root / rel
            if not src.exists():
                src = args.root.parent / rel
            dst = args.dest / rel      # keep the site folder: sites share timestamp filenames
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            count += 1
    print(f"Copied {count} files from {len(by_site)} sites into {args.dest}")


if __name__ == "__main__":
    main()
