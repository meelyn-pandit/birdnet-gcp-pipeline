#!/usr/bin/env python3
"""Copy a small stratified sample (N files per site) for local BirdNET testing.

Example:
    python scripts/pick_sample.py metadata.csv /Volumes/Field/recordings sample/ --per-site 3
"""
import argparse
import csv
import random
import shutil
from collections import defaultdict
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("metadata")
    ap.add_argument("root", type=Path,
                    help="Folder passed to build_metadata.py (a site folder or the folder above it)")
    ap.add_argument("dest", type=Path)
    ap.add_argument("--per-site", type=int, default=3)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    by_site = defaultdict(list)
    with open(args.metadata, newline="") as f:
        for row in csv.DictReader(f):
            if not row["error"]:
                by_site[row["site_id"]].append(row["rel_path"])

    rng = random.Random(args.seed)
    count = 0
    for site, paths in sorted(by_site.items()):
        for rel in rng.sample(paths, min(args.per_site, len(paths))):
            dst = args.dest / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            # rel_path starts with the site folder; root may be that folder or its parent.
            src = args.root / rel
            if not src.exists():
                src = args.root.parent / rel
            shutil.copy2(src, dst)
            count += 1
    print(f"Copied {count} files from {len(by_site)} sites into {args.dest}")


if __name__ == "__main__":
    main()
