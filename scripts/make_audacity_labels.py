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

Example:
    python scripts/make_audacity_labels.py out/ -o labels/
"""
import argparse
import csv
import sys
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", type=Path, help="Folder with BirdNET *.selection.table.txt files")
    ap.add_argument("-o", "--output", type=Path, default=Path("labels"))
    ap.add_argument("--min-conf", type=float, default=0.0,
                    help="Only include detections at or above this confidence")
    ap.add_argument("--force", action="store_true",
                    help="Overwrite existing label files (they may hold your review work)")
    args = ap.parse_args()

    tables = sorted(args.folder.glob("*.selection.table.txt"))
    if not tables:
        sys.exit(f"No *.selection.table.txt files in {args.folder}")
    args.output.mkdir(parents=True, exist_ok=True)

    written = kept = n_labels = 0
    for t in tables:
        stem = t.name.split(".")[0]                 # 20210524_053000.BirdNET.selection.table.txt
        dest = args.output / f"{stem}.txt"
        if dest.exists() and not args.force:
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
        with open(dest, "w") as f:
            for s, e, label in lines:
                f.write(f"{s:.6f}\t{e:.6f}\t{label}\n")
        written += 1
        n_labels += len(lines)

    print(f"Wrote {written} label files ({n_labels} labels) to {args.output}/")
    if kept:
        print(f"Left {kept} existing label files untouched (use --force to overwrite)")


if __name__ == "__main__":
    main()
