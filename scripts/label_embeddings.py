#!/usr/bin/env python3
"""Add labels to a BirdNET/Perch Hoplite embeddings database from annotations.

Each annotation (file, start, end, label) is matched to every 3-second
embedding window in that recording that it overlaps by at least --min-overlap
seconds, and a label row is inserted into hoplite_labels. A point label
(start == end) labels the window containing that point. Recordings are
matched by name without extension (20210524_053000.WAV <-> 20210524_053000).

Input formats (detected automatically; pass any number of files):
  * Audacity label files (.txt, "start<TAB>end<TAB>label" per line). The
    recording is taken from the file name: labels/20210524_053000.txt.
    Label text conventions (see make_audacity_labels.py):
        Indigo Bunting          positive
        - Indigo Bunting        negative (also "neg Indigo Bunting")
        ? Indigo Bunting 0.43   unreviewed, skipped
  * CSV with columns: file, start_s, end_s, label, type[, provenance]
      type   "pos"/"positive" or "neg"/"negative"; rows with a blank type
             are skipped as unreviewed (see make_review_sheet.py)
  * Raven selection table (.txt with a "Selection" header column). Uses
    "Begin Time (s)", "End Time (s)", "Begin Path"/"Begin File", and the
    label from --label-col; every row is treated as positive.

Examples:
    python scripts/label_embeddings.py ./embeddings_db labels/*.txt --provenance meelyn
    python scripts/label_embeddings.py ./embeddings_db review.csv --provenance meelyn
    python scripts/label_embeddings.py ./embeddings_db labels/*.txt --dry-run
"""
import argparse
import csv
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from perch_hoplite.db import interface, sqlite_usearch_impl

POS, NEG = interface.LabelType.POSITIVE, interface.LabelType.NEGATIVE
TYPES = {"pos": POS, "positive": POS, "neg": NEG, "negative": NEG}
UNREVIEWED = object()


def stem(name: str) -> str:
    return Path(name).name.split(".")[0]


def parse_audacity_label(text: str):
    """Return (label, type), or UNREVIEWED, from Audacity label text."""
    text = text.strip()
    if not text or text.startswith("?"):
        return UNREVIEWED
    typ = POS
    m = re.match(r"^(?:-|neg\b|not\b)\s*(.+)$", text, re.IGNORECASE)
    if m:
        text, typ = m.group(1), NEG
    # Drop a trailing BirdNET score left in after removing "?" ("Field Sparrow 0.25").
    text = re.sub(r"\s+[01](?:\.\d+)?$", "", text.strip())
    return text, typ


def read_annotations(path: Path, label_col: str, default_prov: str):
    """Yield dicts with file, start, end, label, type, provenance (or UNREVIEWED)."""
    with open(path, newline="") as f:
        first = f.readline()
        f.seek(0)
        if path.suffix.lower() == ".csv":
            kind = "csv"
        elif first.startswith("Selection\t"):
            kind = "raven"
        else:
            kind = "audacity"

        if kind == "audacity":
            for i, line in enumerate(f, start=1):
                if not line.strip() or line.startswith("\\"):   # "\" lines = spectral selection
                    continue
                parts = line.rstrip("\r\n").split("\t")
                if len(parts) < 3:
                    sys.exit(f"{path}:{i}: expected start<TAB>end<TAB>label, got {line!r}")
                parsed = parse_audacity_label(parts[2])
                if parsed is UNREVIEWED:
                    yield UNREVIEWED
                    continue
                label, typ = parsed
                yield dict(file=stem(path.name), start=float(parts[0]), end=float(parts[1]),
                           label=label, type=typ, provenance=default_prov, where=f"{path.name}:{i}")
            return

        for i, row in enumerate(csv.DictReader(f, delimiter="\t" if kind == "raven" else ","), start=2):
            row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
            if kind == "raven":
                file = row.get("Begin Path") or row.get("Begin File", "")
                start, end, label, typ = row["Begin Time (s)"], row["End Time (s)"], row.get(label_col, ""), "pos"
                if label.lower() == "nocall":
                    continue
            else:
                file, start, end, label = row["file"], row["start_s"], row["end_s"], row["label"]
                typ = row.get("type", "")
                if not typ:
                    yield UNREVIEWED
                    continue
            if typ.lower() not in TYPES:
                sys.exit(f"{path}:{i}: unknown type {typ!r} (use pos or neg)")
            if not (file and label):
                sys.exit(f"{path}:{i}: missing file or label")
            yield dict(file=stem(file), start=float(start), end=float(end), label=label,
                       type=TYPES[typ.lower()], provenance=row.get("provenance") or default_prov,
                       where=f"{path.name}:{i}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("db", help="Embeddings database folder (contains hoplite.sqlite)")
    ap.add_argument("annotations", type=Path, nargs="+",
                    help="Audacity label files, review CSV, or Raven selection tables")
    ap.add_argument("--provenance", default="manual",
                    help="Who/what made the labels, e.g. your name (default: manual)")
    ap.add_argument("--label-col", default="Common Name",
                    help='Raven tables only: column holding the label (default "Common Name")')
    ap.add_argument("--min-overlap", type=float, default=0.5,
                    help="Seconds an annotation must overlap a window to label it (default 0.5)")
    ap.add_argument("--dry-run", action="store_true", help="Show what would be inserted, write nothing")
    args = ap.parse_args()

    missing = [p for p in args.annotations if not p.is_file()]
    if missing:
        sys.exit(f"Annotations file not found: {', '.join(map(str, missing))}\n"
                 "Create label files from BirdNET output first, e.g.:\n"
                 "  python scripts/make_audacity_labels.py out/ -o labels/")
    if not (Path(args.db) / "hoplite.sqlite").exists():
        sys.exit(f"No hoplite.sqlite in {args.db}")
    db = sqlite_usearch_impl.SQLiteUsearchDB.create(args.db)

    # Index embedding windows by recording name: stem -> [(embedding_id, start, end)]
    windows = defaultdict(list)
    for dataset in db.get_dataset_names():
        ids = db.get_embeddings_by_source(dataset, None)
        for emb_id, src in zip(ids, db.get_embedding_sources(ids)):
            windows[stem(src.source_id)].append((int(emb_id), float(src.offsets[0]), float(src.offsets[1])))

    # Collect first: several annotations (e.g. overlapping BirdNET windows from
    # --overlap) can land on the same embedding window. Keyed by
    # (embedding_id, label, provenance) -> {type: description}.
    unreviewed = 0
    unmatched, wanted = [], defaultdict(dict)
    for path in args.annotations:
        for a in read_annotations(path, args.label_col, args.provenance):
            if a is UNREVIEWED:
                unreviewed += 1
                continue
            if a["end"] <= a["start"]:   # point label: the window containing it
                hits = [w for w in windows.get(a["file"], []) if w[1] <= a["start"] < w[2]]
            else:
                # Short calls (e.g. a 0.4 s note) need only overlap by half their length.
                need = min(args.min_overlap, 0.5 * (a["end"] - a["start"]))
                hits = [w for w in windows.get(a["file"], [])
                        if min(a["end"], w[2]) - max(a["start"], w[1]) >= need]
            if not hits:
                unmatched.append(f'{a["where"]} {a["file"]} {a["start"]:g}-{a["end"]:g}s {a["label"]}')
                continue
            for emb_id, ws, we in hits:
                wanted[(emb_id, a["label"], a["provenance"])][a["type"]] = f'{a["file"]} {ws:g}-{we:g}s'

    # Same window marked both positive and negative for a species: the species
    # overlaps the window, so positive wins.
    conflicts = []
    for (emb_id, label, prov), types in wanted.items():
        if POS in types and NEG in types:
            conflicts.append(f"#{emb_id} ({types[POS]}) {label}")
            del types[NEG]

    added = skipped = 0
    per_label, db_conflicts = Counter(), []
    for (emb_id, label, prov), types in sorted(wanted.items()):
        (typ, where), = types.items()
        lab = interface.Label(emb_id, label, typ, prov)
        opposite = NEG if typ is POS else POS
        if any(l.label == label and l.type is opposite for l in db.get_labels(emb_id)):
            db_conflicts.append(f"#{emb_id} ({where}) {label}: already {opposite.name.lower()} in DB")
        if args.dry_run:
            print(f"would label #{emb_id} ({where}) {label} [{typ.name.lower()}]")
            added += 1
        elif db.insert_label(lab, skip_duplicates=True):
            added += 1
        else:
            skipped += 1
        per_label[(label, typ.name.lower())] += 1

    if not args.dry_run:
        db.commit()
    verb = "Would add" if args.dry_run else "Added"
    print(f"{verb} {added} labels from {len(args.annotations)} file(s) "
          f"({skipped} already in DB, {unreviewed} unreviewed skipped)")
    if conflicts:
        print(f"{len(conflicts)} windows were marked both positive and negative for the same "
              f"species; kept positive:", file=sys.stderr)
        for c in conflicts[:20]:
            print("  " + c, file=sys.stderr)
    if db_conflicts:
        print(f"{len(db_conflicts)} labels contradict labels already in the DB (both kept; "
              f"review these):", file=sys.stderr)
        for c in db_conflicts[:20]:
            print("  " + c, file=sys.stderr)
    for (label, typ), n in sorted(per_label.items()):
        print(f"  {label} [{typ}]: {n} windows")
    if unmatched:
        print(f"{len(unmatched)} annotations matched no embedding window "
              f"(recording not in DB, or overlap < {args.min_overlap}s):", file=sys.stderr)
        for u in unmatched[:20]:
            print("  " + u, file=sys.stderr)


if __name__ == "__main__":
    main()
