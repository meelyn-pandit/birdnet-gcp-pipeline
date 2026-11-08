import csv
import random

from birdnet_pipeline.cli.pick_split import candidates, main, pick_aru


def make_aru(folder, days=6):
    folder.mkdir(parents=True)
    for d in range(1, days + 1):
        for hh in ("06", "09"):
            for mm in ("00", "10"):
                (folder / f"202106{d:02d}_{hh}{mm}00.WAV").write_bytes(b"x" * 100)
    (folder / "20210601_060000.BirdNET.results.csv").write_text(
        "common_name,confidence\nA,0.9\nB,0.8\nC,0.2\n")
    (folder / "20210602_060000.WAV").write_bytes(b"x" * 10)      # short file
    (folder / "21060207_003104.WAV").write_bytes(b"x" * 100)     # bad name


def test_candidates_skip_short_and_bad_names(tmp_path):
    make_aru(tmp_path / "aru01")
    recs = candidates("s", tmp_path / "aru01")
    names = {r.path.name for r in recs}
    assert "20210602_060000.WAV" not in names and "21060207_003104.WAV" not in names
    assert {r.stratum for r in recs} == {"202106-dawn", "202106-morning"}
    assert recs[0].recording.startswith("s_aru01_")


def test_pick_aru_no_shared_dates_between_train_and_test(tmp_path):
    make_aru(tmp_path / "aru01")
    picks = pick_aru(candidates("s", tmp_path / "aru01"), 4, 2, 1, 0.5, random.Random(0))
    test_dates = {r.date for r, split, _ in picks if split == "test"}
    train_dates = {r.date for r, split, _ in picks if split == "train"}
    assert len(picks) == 6 and not test_dates & train_dates


def test_main_writes_split_and_copies(tmp_path):
    make_aru(tmp_path / "site" / "aru01")
    make_aru(tmp_path / "site" / "aru02")
    out, dest = tmp_path / "split.csv", tmp_path / "audio"
    main(["--site", f"x={tmp_path / 'site'}", "--exclude", "x/aru02",
          "--train", "3", "--test", "2", "--split-out", str(out), "--dest", str(dest)])
    rows = list(csv.DictReader(open(out)))
    assert len(rows) == 5 and all(r["aru"] == "aru01" for r in rows)
    assert sorted(p.stem for p in dest.iterdir()) == sorted(r["recording"] for r in rows)
