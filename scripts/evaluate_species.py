#!/usr/bin/env python3
"""Compare detectors for one species on held-out test recordings.

Ground truth comes straight from your Audacity label files (labels/<rec>.txt)
on a 3-second window grid, using the same rules as label_embeddings.py:
a window is positive if a confirmed/added label for the species overlaps it
(by >= 0.5 s, or half the label length for short calls), excluded if it only
overlaps a "? <species>" label, and negative otherwise. This assumes every
song of the species was labeled in these recordings.

Methods, all with settings fixed before looking at the test set:
  * BirdNET: its confidence for the species (from selection tables, --birdnet)
  * Perch v2 built-in score for the species (logit), at --perch-cutoffs
  * Classifier on Perch v2 embeddings, trained on the train recordings only

Train/test recordings come from dataset/split.csv. Perch scores each 3 s
window using the 5 s of audio centred on it; results are cached.

With --save, a final classifier is then trained on ALL recordings in the
split (train + test) and saved for running on the archive. The test-set
numbers printed above remain the honest accuracy estimate for it.

Examples:
    python scripts/evaluate_species.py --species "Field Sparrow" \
        --scientific "Spizella pusilla" --birdnet out/
    python scripts/evaluate_species.py --species "Field Sparrow" \
        --scientific "Spizella pusilla" --birdnet out/ --save models/field_sparrow_perch.joblib
"""
import argparse
import csv
import re
import sys
import time
from pathlib import Path

import joblib
import numpy as np
import soundfile as sf
from scipy import signal
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

WIN = 3.0


def overlap(a0, a1, b0, b1):
    return min(a1, b1) - max(a0, b0)


def parse_label(text):
    """Return (species_lower, kind) with kind in pos/neg/unsure."""
    t = text.strip()
    kind = "pos"
    if t.startswith("?"):
        kind = "unsure"
    elif re.match(r"^(-|neg\b|not\b)", t, re.I):
        kind = "neg"
    t = re.sub(r"^(\?|-|neg\b|not\b)\s*", "", t, flags=re.I)
    t = re.sub(r"\s+[01](\.\d+)?$", "", t).strip()
    return t.lower(), kind


def ground_truth(labels_dir, rec, species, n_windows):
    """Array per window: 1 positive, 0 negative, -1 excluded (uncertain)."""
    y = np.zeros(n_windows, dtype=int)
    unsure = np.zeros(n_windows, dtype=bool)
    path = Path(labels_dir) / f"{rec}.txt"
    if not path.exists():
        sys.exit(f"Missing label file {path}")
    for line in path.read_text().splitlines():
        p = line.split("\t")
        if line.startswith("\\") or len(p) < 3:
            continue
        sp, kind = parse_label(p[2])
        if sp != species.lower() or kind == "neg":
            continue
        s, e = float(p[0]), float(p[1])
        for k in range(n_windows):
            w0, w1 = k * WIN, (k + 1) * WIN
            if e <= s:
                hit = w0 <= s < w1
            else:
                hit = overlap(s, e, w0, w1) >= min(0.5, 0.5 * (e - s))
            if hit:
                if kind == "pos":
                    y[k] = 1
                else:
                    unsure[k] = True
    y[(y == 0) & unsure] = -1
    return y


def birdnet_scores(folder, rec, species, n_windows):
    path = Path(folder) / f"{rec}.BirdNET.selection.table.txt"
    out = np.zeros(n_windows)
    if not path.exists():
        sys.exit(f"Missing BirdNET table {path}")
    with open(path, newline="") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            if r.get("Common Name", "").strip().lower() != species.lower():
                continue
            s, e, c = float(r["Begin Time (s)"]), float(r["End Time (s)"]), float(r["Confidence"])
            for k in range(n_windows):
                if overlap(s, e, k * WIN, (k + 1) * WIN) >= WIN / 2:
                    out[k] = max(out[k], c)
    return out


def perch_outputs(model, audio_path, n_windows, class_idx):
    x, sr = sf.read(audio_path)
    if x.ndim > 1:
        x = x.mean(axis=1)
    x = signal.resample_poly(x, 32000, sr).astype(np.float32)
    dur = len(x) / 32000
    frames = []
    for k in range(n_windows):
        c = (k + 0.5) * WIN
        s0 = int(np.clip(c - 2.5, 0, max(0, dur - 5)) * 32000)
        frames.append(x[s0:s0 + 160000])
    out = model.batch_embed(np.stack(frames)[:, None, :])
    logits = np.asarray(out.logits["label"]).reshape(n_windows, -1)[:, class_idx]
    emb = np.asarray(out.embeddings).reshape(n_windows, -1)
    return logits, emb


def summarize(name, y, s, thr):
    m = y >= 0
    y, s = y[m], s[m]
    pred = s >= thr
    tp, fp = int((pred & (y == 1)).sum()), int((pred & (y == 0)).sum())
    prec = tp / (tp + fp) if tp + fp else float("nan")
    rec = tp / y.sum() if y.sum() else float("nan")
    ap = average_precision_score(y, s) if 0 < y.sum() < len(y) else float("nan")
    print(f"  {name:38} found {tp:3}/{int(y.sum()):<3} false alarms {fp:3}   "
          f"precision {prec:4.2f}  recall {rec:4.2f}  AP {ap:4.2f}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--species", required=True, help="Common name as used in labels and BirdNET")
    ap.add_argument("--scientific", required=True, help="Scientific name as used by Perch")
    ap.add_argument("--split", default="dataset/split.csv")
    ap.add_argument("--audio", default="sample", help="Folder with the recordings")
    ap.add_argument("--labels-dir", default="labels")
    ap.add_argument("--birdnet", default="out")
    ap.add_argument("--birdnet-cutoffs", type=float, nargs="+", default=[0.25, 0.10])
    ap.add_argument("--perch-cutoffs", type=float, nargs="+", default=[8, 7, 6])
    ap.add_argument("--clf-threshold", type=float, default=0.5)
    ap.add_argument("--C", type=float, default=0.01)
    ap.add_argument("--cache", default=".cache/perch_eval")
    ap.add_argument("--save", type=Path,
                    help="After evaluating, train on train+test and save the classifier here")
    args = ap.parse_args()

    split = {}
    with open(args.split, newline="") as f:
        for r in csv.DictReader(f):
            split[r["recording"]] = r["split"]
    train = [r for r, s in split.items() if s == "train"]
    test = [r for r, s in split.items() if s == "test"]
    print(f"train: {len(train)} recordings, test: {len(test)} recordings")

    from perch_hoplite.zoo import model_configs
    model = None
    cache = Path(args.cache)
    cache.mkdir(parents=True, exist_ok=True)

    data = {}
    for rec in train + test:
        audio = Path(args.audio) / f"{rec}.WAV"
        if not audio.exists():
            audio = next(Path(args.audio).glob(f"{rec}.*"), audio)
        n = int(sf.info(str(audio)).duration // WIN)
        cf = cache / f"{rec}.npz"
        if cf.exists() and str(np.load(cf)["sci"]) == args.scientific:
            z = np.load(cf); logits, emb = z["logits"], z["emb"]
        else:
            if model is None:
                model = model_configs.load_model_by_name("perch_v2_cpu")
                classes = list(model.class_list["labels"].classes)
                if args.scientific not in classes:
                    sys.exit(f"{args.scientific!r} is not a Perch class")
                cidx = classes.index(args.scientific)
            logits, emb = perch_outputs(model, str(audio), n, cidx)
            np.savez(cf, logits=logits, emb=emb, sci=args.scientific)
        data[rec] = dict(y=ground_truth(args.labels_dir, rec, args.species, n),
                         bn=birdnet_scores(args.birdnet, rec, args.species, n),
                         pl=logits, emb=emb)

    def stack(recs, key):
        return np.concatenate([data[r][key] for r in recs])

    ytr, Etr = stack(train, "y"), stack(train, "emb")
    m = ytr >= 0
    clf = make_pipeline(StandardScaler(), LogisticRegression(C=args.C, class_weight="balanced", max_iter=5000))
    clf.fit(Etr[m], ytr[m])
    for r in test:
        data[r]["clf"] = clf.predict_proba(data[r]["emb"])[:, 1]

    yte = stack(test, "y")
    print(f"training positives: {int((ytr == 1).sum())} windows; "
          f"test: {int((yte == 1).sum())} positive, {int((yte == 0).sum())} negative, "
          f"{int((yte == -1).sum())} excluded windows\n")
    print(f"TEST SET, {args.species} (3 s windows):")
    for c in args.birdnet_cutoffs:
        summarize(f"BirdNET >= {c:g}", yte, stack(test, "bn"), c)
    for c in args.perch_cutoffs:
        summarize(f"Perch built-in score >= {c:g}", yte, stack(test, "pl"), c)
    summarize(f"Classifier on Perch embeddings >= {args.clf_threshold:g}", yte, stack(test, "clf"), args.clf_threshold)

    print("\nper test recording (positives | BirdNET>=0.1 | Perch>=7 | classifier):")
    for r in test:
        d = data[r]; y = d["y"]; ok = y >= 0
        def cell(s, t):
            p = (s >= t) & ok
            return f"{int((p & (y == 1)).sum()):2} found/{int((p & (y == 0)).sum()):2} FA"
        print(f"  {r}: {int((y == 1).sum()):2} | {cell(d['bn'], 0.10)} | {cell(d['pl'], 7)} | "
              f"{cell(d['clf'], args.clf_threshold)}")

    if args.save:
        allr = train + test
        yall, Eall = stack(allr, "y"), stack(allr, "emb")
        m = yall >= 0
        final = make_pipeline(StandardScaler(), LogisticRegression(
            C=args.C, class_weight="balanced", max_iter=5000)).fit(Eall[m], yall[m])
        args.save.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({
            "model": final, "species": args.species, "scientific": args.scientific,
            "threshold": args.clf_threshold, "C": args.C,
            "embedding": "perch_v2_cpu (1536-d), 5 s audio centred on each 3 s window",
            "trained_on": allr, "n_pos": int((yall == 1).sum()), "n_neg": int((yall == 0).sum()),
            "test_estimate": {"recordings": test, "positives": int((yte == 1).sum())},
            "created": time.strftime("%Y-%m-%d %H:%M"),
        }, args.save)
        print(f"\nSaved final classifier trained on all {len(allr)} recordings "
              f"({int((yall == 1).sum())} positive / {int((yall == 0).sum())} negative windows) to {args.save}")


if __name__ == "__main__":
    main()
