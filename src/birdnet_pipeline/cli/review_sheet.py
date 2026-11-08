"""Turn BirdNET selection tables into a review sheet (CSV) for labeling.

Collects every detection into one CSV with an empty `type` column. Listen,
fill in `pos` or `neg`, then load it with bgp-load-labels. Rows left blank
are skipped as unreviewed. Add rows by hand for species BirdNET missed.

(Most review happens in Audacity instead: see bgp-audacity-labels.)

Example:
    bgp-review-sheet
    bgp-review-sheet data/interim/birdnet -o data/annotations/review.csv --min-conf 0.1
"""
import argparse
import csv
import sys
from pathlib import Path

from .. import paths
from ..detectors.birdnet import read_detections, recording_of, selection_tables


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", type=Path, nargs="?", default=paths.BIRDNET_OUT,
                    help="Folder with BirdNET *.selection.table.txt files")
    ap.add_argument("-o", "--output", type=Path, default=paths.REVIEW_CSV)
    ap.add_argument("--min-conf", type=float, default=0.0)
    ap.add_argument("--force", action="store_true", help="Overwrite an existing review sheet")
    args = ap.parse_args(argv)

    tables = selection_tables(args.folder)
    if not tables:
        sys.exit(f"No *.selection.table.txt files in {args.folder}")
    if args.output.exists() and not args.force:
        sys.exit(f"{args.output} exists (it may hold your review work); use --force to overwrite")

    rows = []
    for t in tables:
        for d in read_detections(t):
            if d.confidence >= args.min_conf:
                rows.append(dict(file=recording_of(t), start_s=d.start, end_s=d.end, label=d.common_name,
                                 confidence=f"{d.confidence:.3f}", type="", notes=""))
    rows.sort(key=lambda r: (r["file"], float(r["start_s"]), r["label"]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["file", "start_s", "end_s", "label", "confidence", "type", "notes"])
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} detections from {len(tables)} tables to {args.output}")


if __name__ == "__main__":
    main()
