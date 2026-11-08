"""Write Audacity label files from BirdNET selection tables, ready for review.

One label file per recording (data/annotations/labels/<recording>.txt). Each
BirdNET detection becomes an unreviewed label "? <species> <confidence>".
In Audacity:

    ? Indigo Bunting 0.43   unreviewed BirdNET guess (ignored when loading)
    Indigo Bunting 0.43     confirmed: delete the "?" (the score may stay)
    - Indigo Bunting 0.43   rejected: change "?" to "-"
    Northern Bobwhite       your own label for a call BirdNET missed

Open the WAV, File > Import > Labels... the matching .txt, review, then
Export Labels... back to the same .txt (the name must stay <recording>.txt).

Examples:
    bgp-audacity-labels                 # new label files only; never touches existing ones
    bgp-audacity-labels --merge         # after re-running BirdNET: append only new detections
"""
import argparse
import shutil
import sys
import time
from pathlib import Path

from .. import paths
from ..annotations import audacity_line, overlap, read_audacity, species_key
from ..detectors.birdnet import read_detections, recording_of, selection_tables


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", type=Path, nargs="?", default=paths.BIRDNET_OUT,
                    help="Folder with BirdNET *.selection.table.txt files")
    ap.add_argument("-o", "--output", type=Path, default=paths.LABELS)
    ap.add_argument("--min-conf", type=float, default=0.0,
                    help="Only include detections at or above this confidence")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--merge", action="store_true",
                      help="Append new detections to existing label files without changing "
                           "existing lines; skips detections you already have a label for "
                           "(same species, overlapping). Backs up changed files first.")
    mode.add_argument("--force", action="store_true",
                      help="Overwrite existing label files (DESTROYS your review work)")
    args = ap.parse_args(argv)

    tables = selection_tables(args.folder)
    if not tables:
        sys.exit(f"No *.selection.table.txt files in {args.folder}")
    args.output.mkdir(parents=True, exist_ok=True)
    backup_dir = args.output / f".backup-{time.strftime('%Y%m%d-%H%M%S')}"

    written = kept = n_labels = merged_files = n_merged = n_already = 0
    for t in tables:
        dest = args.output / f"{recording_of(t)}.txt"
        if dest.exists() and not (args.force or args.merge):
            kept += 1
            continue
        lines = sorted((d.start, d.end, f"? {d.common_name} {d.confidence:.2f}", d.common_name)
                       for d in read_detections(t) if d.confidence >= args.min_conf)

        if args.merge and dest.exists():
            existing = read_audacity(dest)
            new = [(s, e, label) for s, e, label, sp in lines
                   if not any(species_key(a.label) == species_key(sp) and overlap(s, e, a.start, a.end) > 0
                              for a in existing)]
            n_already += len(lines) - len(new)
            if new:
                backup_dir.mkdir(exist_ok=True)
                shutil.copy2(dest, backup_dir / dest.name)
                text = dest.read_text()
                with open(dest, "a") as f:
                    if text and not text.endswith("\n"):
                        f.write("\n")
                    f.writelines(audacity_line(s, e, label) for s, e, label in new)
                merged_files += 1
                n_merged += len(new)
            continue

        with open(dest, "w") as f:
            f.writelines(audacity_line(s, e, label) for s, e, label, _ in lines)
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
