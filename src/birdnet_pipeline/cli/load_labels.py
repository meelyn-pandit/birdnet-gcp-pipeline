"""Load annotations into the embeddings database (hoplite_labels).

Each annotation is matched to the 3-second embedding windows of its
recording using the shared rules in birdnet_pipeline.annotations (overlap
>= 0.5 s, or half the call length for short calls; point labels hit the
window containing them). Positive wins when a window is marked both
positive and negative for the same species. Unsure ("?") labels are skipped.

Accepts Audacity label files, the review CSV, or Raven selection tables
(format detected automatically). Passing a folder loads every .txt in it.

Examples:
    bgp-load-labels --dry-run                      # all of data/annotations/labels/
    bgp-load-labels --provenance meelyn
    bgp-load-labels data/annotations/review.csv --provenance meelyn
"""
import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

from .. import paths
from ..annotations import NEG, POS, UNSURE, read_annotations, stem, window_hits


def expand(inputs):
    files = []
    for p in inputs:
        files.extend(sorted(p.glob("*.txt")) if p.is_dir() else [p])
    return files


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("annotations", type=Path, nargs="*", default=[paths.LABELS],
                    help="Annotation files or folders (default: data/annotations/labels/)")
    ap.add_argument("--db", type=Path, default=paths.EMBEDDINGS_DB,
                    help="Embeddings database folder (contains hoplite.sqlite)")
    ap.add_argument("--provenance", default="manual",
                    help="Who/what made the labels, e.g. your name (default: manual)")
    ap.add_argument("--label-col", default="Common Name",
                    help='Raven tables only: column holding the label (default "Common Name")')
    ap.add_argument("--min-overlap", type=float, default=0.5,
                    help="Seconds an annotation must overlap a window to label it (default 0.5)")
    ap.add_argument("--dry-run", action="store_true", help="Show what would be inserted, write nothing")
    args = ap.parse_args(argv)

    files = expand(args.annotations)
    missing = [p for p in files if not p.is_file()]
    if missing or not files:
        sys.exit(f"Annotations file not found: {', '.join(map(str, missing)) or args.annotations}\n"
                 "Create label files from BirdNET output first:  bgp-audacity-labels")
    if not (args.db / "hoplite.sqlite").exists():
        sys.exit(f"No hoplite.sqlite in {args.db}")

    from perch_hoplite.db import interface, sqlite_usearch_impl
    LT = {POS: interface.LabelType.POSITIVE, NEG: interface.LabelType.NEGATIVE}
    db = sqlite_usearch_impl.SQLiteUsearchDB.create(str(args.db))

    # recording stem -> [(embedding_id, start, end)]
    windows = defaultdict(list)
    for dataset in db.get_dataset_names():
        ids = db.get_embeddings_by_source(dataset, None)
        for emb_id, src in zip(ids, db.get_embedding_sources(ids)):
            windows[stem(src.source_id)].append((int(emb_id), float(src.offsets[0]), float(src.offsets[1])))

    # Collect first: several annotations can land on the same embedding window.
    unreviewed, unmatched = 0, []
    wanted = defaultdict(dict)   # (emb_id, label, provenance) -> {kind: "rec s-e"}
    for path in files:
        try:
            anns = read_annotations(path, args.provenance, args.label_col)
        except ValueError as e:
            sys.exit(str(e))
        for a in anns:
            if a.kind == UNSURE:
                unreviewed += 1
                continue
            wins = windows.get(a.recording, [])
            hits = [wins[k] for k in window_hits(a.start, a.end, [(w0, w1) for _, w0, w1 in wins],
                                                 args.min_overlap)]
            if not hits:
                unmatched.append(f"{a.where} {a.recording} {a.start:g}-{a.end:g}s {a.label}")
                continue
            for emb_id, w0, w1 in hits:
                wanted[(emb_id, a.label, a.provenance)][a.kind] = f"{a.recording} {w0:g}-{w1:g}s"

    conflicts = []
    for (emb_id, label, _), kinds in wanted.items():
        if POS in kinds and NEG in kinds:
            conflicts.append(f"#{emb_id} ({kinds[POS]}) {label}")
            del kinds[NEG]

    added = skipped = 0
    per_label, db_conflicts = Counter(), []
    for (emb_id, label, prov), kinds in sorted(wanted.items()):
        (kind, where), = kinds.items()
        opposite = LT[NEG if kind == POS else POS]
        if any(l.label == label and l.type is opposite for l in db.get_labels(emb_id)):
            db_conflicts.append(f"#{emb_id} ({where}) {label}: already {opposite.name.lower()} in DB")
        if args.dry_run:
            print(f"would label #{emb_id} ({where}) {label} [{kind}]")
            added += 1
        elif db.insert_label(interface.Label(emb_id, label, LT[kind], prov), skip_duplicates=True):
            added += 1
        else:
            skipped += 1
        per_label[(label, kind)] += 1

    if not args.dry_run:
        db.commit()
    verb = "Would add" if args.dry_run else "Added"
    print(f"{verb} {added} labels from {len(files)} file(s) "
          f"({skipped} already in DB, {unreviewed} unreviewed skipped)")
    for (label, kind), n in sorted(per_label.items()):
        print(f"  {label} [{kind}]: {n} windows")
    if conflicts:
        print(f"{len(conflicts)} windows were marked both positive and negative for the same "
              f"species; kept positive:", file=sys.stderr)
        for c in conflicts[:20]:
            print("  " + c, file=sys.stderr)
    if db_conflicts:
        print(f"{len(db_conflicts)} labels contradict labels already in the DB (both kept; review these):",
              file=sys.stderr)
        for c in db_conflicts[:20]:
            print("  " + c, file=sys.stderr)
    if unmatched:
        print(f"{len(unmatched)} annotations matched no embedding window "
              f"(recording not in DB, or too little overlap):", file=sys.stderr)
        for u in unmatched[:20]:
            print("  " + u, file=sys.stderr)


if __name__ == "__main__":
    main()
