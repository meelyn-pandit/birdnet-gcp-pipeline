import numpy as np

from birdnet_pipeline import storage
from birdnet_pipeline.cli.detect import output_paths, shard
from birdnet_pipeline.detectors.perch import top_classes


def test_shard_covers_every_recording_exactly_once():
    rows = [{"rel_path": f"aru01/{i:04d}.flac"} for i in range(1960)]
    parts = [shard(rows, i, 20) for i in range(20)]
    seen = [r["rel_path"] for p in parts for r in p]
    assert sorted(seen) == sorted(r["rel_path"] for r in rows)        # all, no duplicates
    assert max(map(len, parts)) - min(map(len, parts)) <= 1           # balanced
    assert shard(list(reversed(rows)), 3, 20) == parts[3]             # independent of input order


def test_top_classes_respects_region_topk_and_floor():
    logits = np.full((2, 10), -5.0)
    logits[0, [1, 2, 3, 9]] = [9.0, 3.0, 1.0, 12.0]   # class 9 is outside the region
    logits[1, 2] = 2.5
    out = top_classes(logits, class_idx=[1, 2, 3, 4], top_k=2, floor=2.0)
    assert out == [(0, 1, 9.0), (0, 2, 3.0), (1, 2, 2.5)]


def test_output_paths_and_join():
    row = {"site_id": "aru01", "rel_path": "aru01/20210524_053000.flac"}
    det, emb = output_paths("gs://b/derived", row)
    assert det == "gs://b/derived/detections/aru01/20210524_053000.csv"
    assert emb == "gs://b/derived/embeddings/aru01/20210524_053000.npz"
    assert storage.join("gs://b/derived/", "/x/", "y.csv") == "gs://b/derived/x/y.csv"


def test_local_storage_roundtrip(tmp_path):
    p = tmp_path / "a" / "b.txt"
    storage.write_bytes(p, b"hello")
    assert storage.exists(p) and storage.read_text(p) == "hello"
    assert not list(tmp_path.rglob("*.part"))
