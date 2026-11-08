"""Detect all species in recordings with BirdNET, Perch and species classifiers.

Designed to run as a Cloud Run Job: each task processes its share of the
recordings in the metadata table (CLOUD_RUN_TASK_INDEX / CLOUD_RUN_TASK_COUNT),
reading audio and writing results at local paths or gs:// URIs. Recordings
whose output already exists are skipped, so a job can be re-run to resume.

Per recording it writes
  <out>/detections/<site>/<recording>.csv   one row per (window, method, species)
  <out>/embeddings/<site>/<recording>.npz   Perch embeddings for every window
with methods:
  birdnet     BirdNET confidence (0-1), using the recording's own lat/lon/week
  perch       Perch logit, top-k regional classes per window (configs/region.toml)
  classifier  probability from each classifier bundle listed in region.toml

Examples:
    bgp-detect --metadata data/processed/metadata.csv --audio data/raw/flac --out data/interim/detect --limit 3
    bgp-detect --metadata gs://BUCKET/metadata/recordings.csv --audio gs://BUCKET/raw --out gs://BUCKET/derived
"""
import argparse
import csv
import io
import os
import sys
import tempfile
import time
import tomllib
from collections import defaultdict
from pathlib import Path

import numpy as np

from .. import paths, storage
from ..annotations import grid_windows, stem

FIELDS = ["recording_id", "rel_path", "site_id", "start_utc", "start_s", "end_s", "method", "model",
          "species_scientific", "species_common", "score", "score_type"]


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def shard(rows, index: int, count: int):
    """Deterministic share of rows for task `index` of `count` (sorted by rel_path)."""
    rows = sorted(rows, key=lambda r: r["rel_path"])
    return [r for i, r in enumerate(rows) if i % count == index]


def output_paths(out, row):
    site, rec = row["site_id"], stem(row["rel_path"])
    return (storage.join(out, "detections", site, f"{rec}.csv"),
            storage.join(out, "embeddings", site, f"{rec}.npz"))


def regional_classes(sites, perch_names, threshold, extras):
    """Perch class indices for birds expected at any site (BirdNET location model) + extra classes."""
    from ..detectors.birdnet import species_list

    wanted = set()
    for lat, lon in sites:
        wanted.update(sci for sci, _ in species_list(lat, lon, -1, threshold))
    unknown_extras = [e for e in extras if e not in perch_names]
    wanted.update(e for e in extras if e in perch_names)
    idx = sorted(perch_names.index(s) for s in wanted if s in perch_names)
    return idx, len(wanted), unknown_extras


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--metadata", default=str(paths.METADATA_CSV), help="Metadata CSV (local or gs://)")
    ap.add_argument("--audio", default=str(paths.RAW / "flac"),
                    help="Root that rel_path is relative to (local or gs://, e.g. gs://BUCKET/raw)")
    ap.add_argument("--out", default=str(paths.INTERIM / "detect"), help="Output root (local or gs://)")
    ap.add_argument("--config", type=Path, default=paths.CONFIGS / "region.toml")
    ap.add_argument("--task-index", type=int, default=int(os.environ.get("CLOUD_RUN_TASK_INDEX", 0)))
    ap.add_argument("--task-count", type=int, default=int(os.environ.get("CLOUD_RUN_TASK_COUNT", 1)))
    ap.add_argument("--limit", type=int, help="Process at most this many recordings (testing)")
    ap.add_argument("--overwrite", action="store_true", help="Redo recordings that already have output")
    ap.add_argument("--threads", type=int, default=os.cpu_count() or 4)
    args = ap.parse_args(argv)

    cfg = tomllib.loads(args.config.read_text())
    reg, det = cfg["region"], cfg["detect"]
    win = float(det.get("window_s", 3.0))

    all_rows = [r for r in csv.DictReader(io.StringIO(storage.read_text(args.metadata))) if not r["error"]]
    sites = sorted({(float(r["latitude"]), float(r["longitude"])) for r in all_rows if r["latitude"]})
    mine = shard(all_rows, args.task_index, args.task_count)
    if not args.overwrite:
        mine = [r for r in mine if not storage.exists(output_paths(args.out, r)[0])]
    if args.limit:
        mine = mine[:args.limit]
    log(f"task {args.task_index}/{args.task_count}: {len(mine)} recordings to process "
        f"({len(all_rows)} in metadata, {len(sites)} site locations)")
    if not mine:
        return

    from ..classifier import load_bundle
    from ..detectors import birdnet, perch

    log("loading Perch")
    model = perch.load_model()
    names = perch.class_names(model)
    common = birdnet.label_names()
    region_idx, n_wanted, unknown = regional_classes(sites, names, reg.get("birdnet_species_threshold", 0.03),
                                                     reg.get("extra_perch_classes", []))
    log(f"regional list: {len(region_idx)} Perch classes ({n_wanted} wanted)")
    if unknown:
        log(f"WARNING: not Perch classes, skipped: {', '.join(unknown)}")

    classifiers = []
    for src in det.get("classifiers", []):
        with tempfile.TemporaryDirectory() as td:
            b = load_bundle(storage.download(src, Path(td) / "model.joblib"))
        classifiers.append(b)
        log(f"classifier: {b['species']} (threshold {b['threshold']})")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        # Download audio, grouped by BirdNET location/week.
        groups = defaultdict(list)
        for r in mine:
            key = (r["latitude"] or "-1", r["longitude"] or "-1", r["birdnet_week"] or "-1")
            local = tmp / "audio" / "_".join(key) / Path(r["rel_path"]).name
            storage.download(storage.join(args.audio, r["rel_path"]), local)
            groups[key].append(r)
        log(f"downloaded {len(mine)} recordings in {len(groups)} location/week groups")

        bn = defaultdict(list)
        for key, rows in groups.items():
            lat, lon, week = key
            for d in birdnet.run_analyzer(tmp / "audio" / "_".join(key), tmp / "birdnet" / "_".join(key),
                                          float(lat), float(lon), int(week),
                                          det.get("birdnet_min_conf", 0.1), 0.0, args.threads):
                bn[d.recording].append(d)
        log(f"BirdNET: {sum(len(v) for v in bn.values())} detections")

        for n, r in enumerate(mine, 1):
            rec = stem(r["rel_path"])
            key = (r["latitude"] or "-1", r["longitude"] or "-1", r["birdnet_week"] or "-1")
            local = tmp / "audio" / "_".join(key) / Path(r["rel_path"]).name
            n_win = int(float(r["duration_s"]) // win)
            windows = grid_windows(n_win, win)
            base = {k: r[k] for k in ("recording_id", "rel_path", "site_id", "start_utc")}
            out_rows = []
            for d in bn.get(rec, []):
                out_rows.append({**base, "start_s": d.start, "end_s": d.end, "method": "birdnet",
                                 "model": "BirdNET_GLOBAL_6K_V2.4", "species_scientific": d.scientific,
                                 "species_common": d.common, "score": round(d.confidence, 4),
                                 "score_type": "confidence"})
            logits, emb = perch.all_outputs(model, local, windows)
            for w, c, s in perch.top_classes(logits, region_idx, det.get("perch_top_k", 5),
                                             det.get("perch_logit_floor", 2.0)):
                out_rows.append({**base, "start_s": windows[w][0], "end_s": windows[w][1], "method": "perch",
                                 "model": perch.MODEL_NAME, "species_scientific": names[c],
                                 "species_common": common.get(names[c], ""), "score": round(s, 3),
                                 "score_type": "logit"})
            for b in classifiers:
                prob = b["model"].predict_proba(emb)[:, 1]
                for w in np.where(prob >= det.get("classifier_floor", 0.05))[0]:
                    out_rows.append({**base, "start_s": windows[w][0], "end_s": windows[w][1],
                                     "method": "classifier", "model": f"{b['species']} ({b.get('created', '')})",
                                     "species_scientific": b.get("scientific", ""), "species_common": b["species"],
                                     "score": round(float(prob[w]), 4), "score_type": "probability"})

            det_path, emb_path = output_paths(args.out, r)
            buf = io.BytesIO()
            np.savez_compressed(buf, embeddings=emb.astype(np.float16),
                                window_start_s=np.array([w0 for w0, _ in windows], dtype=np.float32))
            storage.write_bytes(emb_path, buf.getvalue())
            text = io.StringIO()
            w = csv.DictWriter(text, fieldnames=FIELDS, lineterminator="\n")
            w.writeheader()
            w.writerows(out_rows)
            storage.write_bytes(det_path, text.getvalue().encode(), "text/csv")   # written last = done marker
            if n % 10 == 0 or n == len(mine):
                log(f"{n}/{len(mine)} recordings done")
    log("finished")


if __name__ == "__main__":
    sys.exit(main())
