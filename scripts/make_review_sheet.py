#!/usr/bin/env python3
"""Turn BirdNET selection tables into a review sheet for labeling.

Collects every detection from BirdNET's --rtype table output into one CSV
with an empty `type` column. Listen to each detection, fill in `pos` (the
species is there) or `neg` (it is not), then load the sheet with
label_embeddings.py. Rows left blank are skipped as unreviewed.

You can also add rows by hand for species BirdNET missed (type = pos).

Example:
    python scripts/make_review_sheet.py out/ -o review.csv
    # ...listen and fill in the type column...
    python scripts/label_embeddings.py ./embeddings_db review.csv --provenance meelyn
"""
import argparse
import csv
import sys
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", type=Path, help="Folder with *.selection.table.txt files")
    ap.add_argument("-o", "--output", type=Path, default=Path("review.csv"))
    ap.add_argument("--min-conf", type=float, default=0.0,
                    help="Only include detections at or above this confidence")
    ap.add_argument("--force", action="store_true", help="Overwrite an existing output file")
    args = ap.parse_args()

    tables = sorted(args.folder.glob("*.selection.table.txt"))
    if not tables:
        sys.exit(f"No *.selection.table.txt files in {args.folder}")
    if args.output.exists() and not args.force:
        sys.exit(f"{args.output} exists (it may hold your review work); use --force to overwrite")

    rows = []
    for t in tables:
        with open(t, newline="") as f:
            for r in csv.DictReader(f, delimiter="\t"):
                name = r.get("Common Name", "").strip()
                conf = float(r.get("Confidence") or 0)
                if not name or name.lower() == "nocall" or conf < args.min_conf:
                    continue
                rows.append(dict(file=Path(r.get("Begin Path") or r.get("Begin File", "")).name,
                                 start_s=r["Begin Time (s)"], end_s=r["End Time (s)"],
                                 label=name, confidence=f"{conf:.3f}", type="", notes=""))

    rows.sort(key=lambda r: (r["file"], float(r["start_s"]), r["label"]))
    with open(args.output, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["file", "start_s", "end_s", "label", "confidence", "type", "notes"])
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} detections from {len(tables)} tables to {args.output}")


if __name__ == "__main__":
    main()
