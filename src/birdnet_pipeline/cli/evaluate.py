"""Compare detectors for one species on held-out test recordings.

Ground truth comes from your Audacity label files on a 3-second window grid,
using the shared rules in birdnet_pipeline.annotations. This assumes every
song of the species was labeled in the train and test recordings.

Methods, all with settings fixed in configs/species.toml before testing:
  * BirdNET: its confidence for the species (from selection tables)
  * Perch v2 built-in score for the species, at the configured cutoffs
  * Classifier on Perch v2 embeddings, trained on the train recordings only

Train/test recordings come from data/splits/split.csv. Results are saved to
reports/<species>_<timestamp>.json. With --save, a final classifier is
trained on ALL split recordings (train + test) and saved; the test numbers
remain the honest accuracy estimate for it.

Examples:
    bgp-evaluate --species "Field Sparrow"
    bgp-evaluate --species "Field Sparrow" --save models/field_sparrow_perch.joblib
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

from .. import paths
from ..annotations import grid_windows, ground_truth, read_audacity
from ..classifier import make_classifier, save_bundle
from ..config import slug, species_settings
from ..detectors.birdnet import read_detections, table_path, window_scores
from ..detectors.perch import MODEL_NAME, CachedPerch
from ..evaluation import find_audio, format_row, metrics, read_split

WIN = 3.0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--species", required=True, help="Common name as used in labels and BirdNET")
    ap.add_argument("--scientific", help="Scientific name used by Perch (default: configs/species.toml)")
    ap.add_argument("--split", type=Path, default=paths.SPLIT_CSV)
    ap.add_argument("--audio", type=Path, default=paths.RAW_SAMPLE, help="Folder with the recordings")
    ap.add_argument("--labels-dir", type=Path, default=paths.LABELS)
    ap.add_argument("--birdnet", type=Path, default=paths.BIRDNET_OUT)
    ap.add_argument("--birdnet-cutoffs", type=float, nargs="+", default=[0.25, 0.10])
    ap.add_argument("--perch-cutoffs", type=float, nargs="+")
    ap.add_argument("--clf-threshold", type=float)
    ap.add_argument("--C", type=float)
    ap.add_argument("--cache", type=Path, default=paths.PERCH_CACHE)
    ap.add_argument("--report", type=Path, help="Where to save results JSON (default: reports/...)")
    ap.add_argument("--save", type=Path, help="Train on train+test and save the classifier here")
    args = ap.parse_args(argv)

    cfg = species_settings(args.species)
    scientific = args.scientific or cfg.get("scientific")
    if not scientific:
        sys.exit(f"No scientific name for {args.species!r}: pass --scientific or add it to configs/species.toml")
    perch_cutoffs = args.perch_cutoffs or cfg["perch_cutoffs"]
    clf_thr = args.clf_threshold if args.clf_threshold is not None else cfg["classifier_threshold"]
    C = args.C if args.C is not None else cfg["classifier_C"]

    split = read_split(args.split)
    train = [r for r, s in split.items() if s == "train"]
    test = [r for r, s in split.items() if s == "test"]
    print(f"{args.species} ({scientific}): train {len(train)} recordings, test {len(test)} recordings")

    import soundfile as sf
    perch = CachedPerch(args.cache, scientific)
    data = {}
    for rec in train + test:
        audio = find_audio(args.audio, rec)
        windows = grid_windows(int(sf.info(str(audio)).duration // WIN), WIN)
        label_file = args.labels_dir / f"{rec}.txt"
        if not label_file.exists():
            sys.exit(f"Missing label file {label_file}")
        bn_table = table_path(args.birdnet, rec)
        if not bn_table.exists():
            sys.exit(f"Missing BirdNET table {bn_table}")
        logits, emb = perch.outputs(rec, audio, windows)
        data[rec] = dict(y=ground_truth(read_audacity(label_file), args.species, windows),
                         bn=window_scores(read_detections(bn_table), args.species, windows),
                         pl=logits, emb=emb)

    def stack(recs, key):
        return np.concatenate([data[r][key] for r in recs])

    ytr, Etr = stack(train, "y"), stack(train, "emb")
    clf = make_classifier(C).fit(Etr[ytr >= 0], ytr[ytr >= 0])
    for r in test:
        data[r]["clf"] = clf.predict_proba(data[r]["emb"])[:, 1]

    yte = stack(test, "y")
    print(f"training positives: {int((ytr == 1).sum())} windows; test: {int((yte == 1).sum())} positive, "
          f"{int((yte == 0).sum())} negative, {int((yte == -1).sum())} excluded windows\n")
    print(f"TEST SET, {args.species} (3 s windows):")
    results = {}
    for c in args.birdnet_cutoffs:
        results[f"BirdNET >= {c:g}"] = metrics(yte, stack(test, "bn"), c)
    for c in perch_cutoffs:
        results[f"Perch built-in score >= {c:g}"] = metrics(yte, stack(test, "pl"), c)
    results[f"Classifier on Perch embeddings >= {clf_thr:g}"] = metrics(yte, stack(test, "clf"), clf_thr)
    for name, m in results.items():
        print(format_row(name, m))

    print("\nper test recording (positives | BirdNET>=0.1 | Perch>=7 | classifier):")
    per_rec = {}
    for r in test:
        d = data[r]
        per_rec[r] = {"positives": int((d["y"] == 1).sum()),
                      "birdnet_0.1": metrics(d["y"], d["bn"], 0.10),
                      "perch_7": metrics(d["y"], d["pl"], 7),
                      "classifier": metrics(d["y"], d["clf"], clf_thr)}
        cell = lambda m: f"{m['found']:2} found/{m['false_alarms']:2} FA"
        p = per_rec[r]
        print(f"  {r}: {p['positives']:2} | {cell(p['birdnet_0.1'])} | {cell(p['perch_7'])} | "
              f"{cell(p['classifier'])}")

    report = {"species": args.species, "scientific": scientific, "created": time.strftime("%Y-%m-%d %H:%M"),
              "split": {"train": train, "test": test}, "window_s": WIN, "perch_model": MODEL_NAME,
              "classifier": {"C": C, "threshold": clf_thr},
              "test": results, "per_test_recording": per_rec}
    report_path = args.report or paths.REPORTS / f"{slug(args.species)}_{time.strftime('%Y%m%d-%H%M%S')}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, default=float))
    print(f"\nSaved results to {report_path}")

    if args.save:
        allr = train + test
        yall, Eall = stack(allr, "y"), stack(allr, "emb")
        final = make_classifier(C).fit(Eall[yall >= 0], yall[yall >= 0])
        save_bundle(args.save, final, species=args.species, scientific=scientific, threshold=clf_thr, C=C,
                    embedding=f"{MODEL_NAME} (1536-d), 5 s audio centred on each 3 s window",
                    trained_on=allr, n_pos=int((yall == 1).sum()), n_neg=int((yall == 0).sum()),
                    test_estimate=results[f"Classifier on Perch embeddings >= {clf_thr:g}"],
                    report=str(report_path))
        print(f"Saved final classifier trained on all {len(allr)} recordings "
              f"({int((yall == 1).sum())} positive / {int((yall == 0).sum())} negative windows) to {args.save}")


if __name__ == "__main__":
    main()
