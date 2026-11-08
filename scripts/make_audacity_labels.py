#!/usr/bin/env python3
"""Write Audacity label files from BirdNET selection tables, ready for review.

One label file per recording (labels/20210524_053000.txt). Each BirdNET
detection becomes an unreviewed label "? <species> <confidence>". In Audacity:

    ? Indigo Bunting 0.43   unreviewed BirdNET guess (ignored when loading)
    Indigo Bunting          confirmed: delete the "? " and the score
    - Indigo Bunting        rejected: change "?" to "-"
    Northern Bobwhite       your own label for a call BirdNET missed

In Audacity: File > Open the WAV, File > Import > Labels... the matching .txt,
review, then File > Export Other > Export Labels... back to the same .txt
(the file name must stay <recording name>.txt). Then load all of them:

    python scripts/label_embeddings.py ./embeddings_db labels/*.txt --provenance meelyn

Examples:
    python scripts/make_audacity_labels.py out/ -o labels/
    # after re-running BirdNET (e.g. lower --min_conf), add only the new detections:
    python scripts/make_audacity_labels.py out/ -o labels/ --merge
"""
import argparse
import csv
import re
import shutil
import sys
import time
from pathlib import Path


def species_of(label_text: str) -> str:
    """Species name from label text, ignoring ?/-/neg prefixes and a trailing score."""
    t = re.sub(r"^(?:\?|-|neg\b|not\b)\s*", "", label_text.strip(), flags=re.IGNORECASE)
    return re.sub(r"\s+[01](?:\.\d+)?$", "", t).strip().lower()


def read_existing(path: Path):
    """(start, end, species) for every label already in an Audacity label file."""
    out = []
    for line in path.read_text().splitlines():
        parts = line.split("\t")
        if line.startswith("\\") or len(parts) < 3:
            continue
        try:
            out.append((float(parts[0]), float(parts[1]), species_of(parts[2])))
        except ValueError:
            continue
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", type=Path, help="Folder with BirdNET *.selection.table.txt files")
    ap.add_argument("-o", "--output", type=Path, default=Path("labels"))
    ap.add_argument("--min-conf", type=float, default=0.0,
                    help="Only include detections at or above this confidence")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--merge", action="store_true",
                      help="Append new detections to existing label files without changing "
                           "existing lines; skips detections you already have a label for "
                           "(same species, overlapping). Backs up files first.")
    mode.add_argument("--force", action="store_true",
                      help="Overwrite existing label files (DESTROYS your review work)")
    args = ap.parse_args()

    tables = sorted(args.folder.glob("*.selection.table.txt"))
    if not tables:
        sys.exit(f"No *.selection.table.txt files in {args.folder}")
    args.output.mkdir(parents=True, exist_ok=True)
    backup_dir = args.output / f".backup-{time.strftime('%Y%m%d-%H%M%S')}"

    written = kept = n_labels = merged_files = n_merged = n_already = 0
    for t in tables:
        stem = t.name.split(".")[0]                 # 20210524_053000.BirdNET.selection.table.txt
        dest = args.output / f"{stem}.txt"
        if dest.exists() and not (args.force or args.merge):
            kept += 1
            continue
        lines = []
        with open(t, newline="") as f:
            for r in csv.DictReader(f, delimiter="\t"):
                name = r.get("Common Name", "").strip()
                conf = float(r.get("Confidence") or 0)
                if not name or name.lower() == "nocall" or conf < args.min_conf:
                    continue
                lines.append((float(r["Begin Time (s)"]), float(r["End Time (s)"]), f"? {name} {conf:.2f}"))
        lines.sort()

        if args.merge and dest.exists():
            existing = read_existing(dest)
            new = []
            for s, e, label in lines:
                sp = species_of(label)
                if any(es == sp and min(e, ee) > max(s, xs) for xs, ee, es in existing):
                    n_already += 1
                    continue
                new.append((s, e, label))
            if new:
                backup_dir.mkdir(exist_ok=True)
                shutil.copy2(dest, backup_dir / dest.name)
                text = dest.read_text()
                with open(dest, "a") as f:
                    if text and not text.endswith("\n"):
                        f.write("\n")
                    for s, e, label in new:
                        f.write(f"{s:.6f}\t{e:.6f}\t{label}\n")
                merged_files += 1
                n_merged += len(new)
            continue

        with open(dest, "w") as f:
            for s, e, label in lines:
                f.write(f"{s:.6f}\t{e:.6f}\t{label}\n")
        written += 1
        n_labels += len(lines)

    print(f"Wrote {written} new label files ({n_labels} labels) to {args.output}/")
    if args.merge:
        print(f"Merged {n_merged} new detections into {merged_files} existing files; "
              f"skipped {n_already} you already have labels for")
        if merged_files:
            print(f"Backups of changed files: {backup_dir}/")
    if kept:
        print(f"Left {kept} existing label files untouched (use --merge to add new detections)")


if __name__ == "__main__":
    main()
