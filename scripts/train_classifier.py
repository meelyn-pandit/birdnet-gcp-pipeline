#!/usr/bin/env python3
"""Train a one-species classifier on BirdNET embeddings and compare it with BirdNET.

Positives: windows labeled positive for --species in hoplite_labels.
Negatives: every other window in the fully reviewed recordings (--files),
excluding windows overlapping a "? <species>" (uncertain) label in the
Audacity label files. This assumes you labeled EVERY song of the species
in those recordings.

Evaluation is leave-one-recording-out: train on all reviewed recordings but
one, score the held-out one, repeat. BirdNET is scored on the same windows
from its selection tables (--birdnet), so the comparison is like for like.
A final model trained on all reviewed recordings is saved with --save.

Example:
    python scripts/train_classifier.py ./embeddings_db --species "Field Sparrow" \
        --files 20210524_071000 20210620_071000 20210626_075000 20210730_054000 20210805_073000 \
        --birdnet out/ --save models/field_sparrow.joblib
"""
import argparse
import csv
import re
import sys
import time
from pathlib import Path

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, precision_recall_fscore_support
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from perch_hoplite.db import interface, sqlite_usearch_impl


def stem(name):
    return Path(name).name.split(".")[0]


def overlap(a0, a1, b0, b1):
    return min(a1, b1) - max(a0, b0)


def uncertain_spans(labels_dir, rec, species):
    """(start, end) of '? <species>' labels in labels/<rec>.txt."""
    path = Path(labels_dir) / f"{rec}.txt"
    spans = []
    if path.exists():
        for line in path.read_text().splitlines():
            p = line.split("\t")
            if len(p) >= 3 and p[2].strip().startswith("?"):
                sp = re.sub(r"^\?\s*|\s+[01](?:\.\d+)?$", "", p[2].strip())
                if sp.lower() == species.lower():
                    spans.append((float(p[0]), float(p[1])))
    return spans


def birdnet_scores(folder, rec, species, windows):
    """Max BirdNET confidence for species over detections covering >= half of each window."""
    path = Path(folder) / f"{rec}.BirdNET.selection.table.txt"
    dets = []
    if path.exists():
        with open(path, newline="") as f:
            for r in csv.DictReader(f, delimiter="\t"):
                if r.get("Common Name", "").strip().lower() == species.lower():
                    dets.append((float(r["Begin Time (s)"]), float(r["End Time (s)"]), float(r["Confidence"])))
    return np.array([max([c for s, e, c in dets if overlap(s, e, w0, w1) >= (w1 - w0) / 2] or [0.0])
                     for w0, w1 in windows])


def prf(y, pred):
    p, r, f, _ = precision_recall_fscore_support(y, pred, average="binary", zero_division=0)
    return p, r, f


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("db", help="Embeddings database folder")
    ap.add_argument("--species", required=True)
    ap.add_argument("--files", nargs="+", required=True, help="Fully reviewed recording names (no extension)")
    ap.add_argument("--labels-dir", default="labels", help="Audacity label files, for '?' exclusions")
    ap.add_argument("--birdnet", help="Folder of BirdNET selection tables for comparison")
    ap.add_argument("--threshold", type=float, default=0.5, help="Classifier score threshold")
    ap.add_argument("--C", type=float, default=0.1, help="Inverse regularization strength")
    ap.add_argument("--save", type=Path, help="Save the final model (joblib)")
    args = ap.parse_args()

    db = sqlite_usearch_impl.SQLiteUsearchDB.create(args.db)
    pos_ids = set(int(i) for i in db.get_embeddings_by_label(args.species, interface.LabelType.POSITIVE))
    files = [stem(f) for f in args.files]

    ids, recs, wins = [], [], []
    for dataset in db.get_dataset_names():
        all_ids = db.get_embeddings_by_source(dataset, None)
        for emb_id, src in zip(all_ids, db.get_embedding_sources(all_ids)):
            r = stem(src.source_id)
            if r in files:
                ids.append(int(emb_id)); recs.append(r)
                wins.append((float(src.offsets[0]), float(src.offsets[1])))
    missing = sorted(set(files) - set(recs))
    if missing:
        sys.exit(f"Recordings not in the embeddings DB: {', '.join(missing)}")

    n_total = len(ids)
    keep = []
    for k, (r, (w0, w1)) in enumerate(zip(recs, wins)):
        unsure = any(overlap(s, e, w0, w1) > 0 for s, e in uncertain_spans(args.labels_dir, r, args.species))
        if ids[k] in pos_ids or not unsure:
            keep.append(k)
    ids = [ids[k] for k in keep]; recs = np.array([recs[k] for k in keep]); wins = [wins[k] for k in keep]
    X = np.array([db.get_embedding(i) for i in ids], dtype=np.float32)
    y = np.array([i in pos_ids for i in ids], dtype=int)
    print(f"{args.species}: {y.sum()} positive / {len(y) - y.sum()} negative windows "
          f"from {len(files)} recordings ({len(keep)} used, "
          f"{n_total - len(keep)} excluded as uncertain)\n")
    if y.sum() < 5:
        sys.exit("Too few positives to train.")

    def model():
        return make_pipeline(StandardScaler(), LogisticRegression(
            C=args.C, class_weight="balanced", max_iter=5000))

    oof = np.zeros(len(y))
    for r in files:
        test = recs == r
        train = ~test
        if y[train].sum() == 0 or y[train].sum() == train.sum():
            continue
        oof[test] = model().fit(X[train], y[train]).predict_proba(X[test])[:, 1]

    rows = [("Your classifier", oof, args.threshold)]
    if args.birdnet:
        bn = np.concatenate([birdnet_scores(args.birdnet, r, args.species,
                                            [w for w, rr in zip(wins, recs) if rr == r]) for r in files])
        order = np.concatenate([np.where(recs == r)[0] for r in files])
        bn_aligned = np.zeros(len(y)); bn_aligned[order] = bn
        rows += [("BirdNET @ 0.25", bn_aligned, 0.25), ("BirdNET @ 0.10", bn_aligned, 0.10)]

    print(f"{'leave-one-recording-out':24} {'precision':>9} {'recall':>7} {'F1':>6} {'found':>7} {'false+':>6} {'AP':>6}")
    for name, s, thr in rows:
        pred = (s >= thr).astype(int)
        p, r, f = prf(y, pred)
        print(f"{name:24} {p:9.2f} {r:7.2f} {f:6.2f} {f'{(pred & y).sum()}/{y.sum()}':>7} "
              f"{(pred & (1 - y)).sum():>6} {average_precision_score(y, s):6.2f}")
    print("\nper recording (your classifier):")
    for r in files:
        m = recs == r
        pred = (oof[m] >= args.threshold).astype(int)
        print(f"  {r}: {y[m].sum():2} songs-windows, found {(pred & y[m]).sum():2}, false+ {(pred & (1 - y[m])).sum():2}")

    if args.save:
        final = model().fit(X, y)
        args.save.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"model": final, "species": args.species, "threshold": args.threshold,
                     "trained_on": files, "n_pos": int(y.sum()), "n_neg": int(len(y) - y.sum()),
                     "embedding": "BirdNET V2.4 (1024-d, 3 s windows)", "C": args.C,
                     "created": time.strftime("%Y-%m-%d %H:%M")}, args.save)
        print(f"\nSaved final model (trained on all {len(files)} recordings) to {args.save}")


if __name__ == "__main__":
    main()
