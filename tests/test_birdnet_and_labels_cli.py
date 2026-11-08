from birdnet_pipeline.annotations import grid_windows
from birdnet_pipeline.cli import audacity_labels
from birdnet_pipeline.detectors.birdnet import Detection, read_detections, window_scores

HEADER = ("Selection\tView\tChannel\tBegin Time (s)\tEnd Time (s)\tLow Freq (Hz)\tHigh Freq (Hz)\t"
          "Common Name\tSpecies Code\tConfidence\tBegin Path\tFile Offset (s)\n")


def table(tmp_path, rec, rows):
    d = tmp_path / "birdnet"
    d.mkdir(exist_ok=True)
    lines = [f"{i}\tSpectrogram 1\t1\t{s}\t{e}\t0\t15000\t{n}\tx\t{c}\t/x/{rec}.WAV\t{s}\n"
             for i, (s, e, n, c) in enumerate(rows, 1)]
    (d / f"{rec}.BirdNET.selection.table.txt").write_text(HEADER + "".join(lines))
    return d


def test_read_detections_skips_nocall(tmp_path):
    d = table(tmp_path, "r1", [(0, 3, "nocall", 1.0), (18, 21, "Field Sparrow", 0.25)])
    dets = read_detections(d / "r1.BirdNET.selection.table.txt")
    assert dets == [Detection(18.0, 21.0, "Field Sparrow", 0.25)]


def test_window_scores_half_overlap():
    W = grid_windows(10)
    dets = [Detection(19, 22, "Field Sparrow", 0.4), Detection(20, 23, "Field Sparrow", 0.6),
            Detection(4, 7, "Indigo Bunting", 0.9)]
    s = window_scores(dets, "Field Sparrow", W)
    assert s[6] == 0.4          # 18-21: 19-22 covers 2 s; 20-23 covers only 1 s
    assert s[7] == 0.6          # 21-24: 20-23 covers 2 s
    assert s[1] == 0            # other species ignored


def test_new_label_files_and_no_overwrite(tmp_path):
    d = table(tmp_path, "r1", [(18, 21, "Field Sparrow", 0.25)])
    out = tmp_path / "labels"
    audacity_labels.main([str(d), "-o", str(out)])
    assert (out / "r1.txt").read_text() == "18.000000\t21.000000\t? Field Sparrow 0.25\n"
    (out / "r1.txt").write_text("my review\t\t\n")
    audacity_labels.main([str(d), "-o", str(out)])               # default: never touches existing
    assert (out / "r1.txt").read_text() == "my review\t\t\n"


def test_merge_appends_only_new_and_never_changes_existing(tmp_path):
    out = tmp_path / "labels"
    out.mkdir()
    reviewed = ("18.000000\t21.000000\tField Sparrow 0.25\n"
                "60.000000\t63.000000\t- Yellow-billed Cuckoo 0.98\n"
                "26.143223\t28.283030\tIndigo Bunting\n")
    (out / "r1.txt").write_text(reviewed)
    d = table(tmp_path, "r1", [(18, 21, "Field Sparrow", 0.25),        # already confirmed
                               (61, 64, "Yellow-billed Cuckoo", 0.9),  # already rejected (overlaps)
                               (26, 29, "Indigo Bunting", 0.13),       # covered by my tight label
                               (90, 93, "Blue Grosbeak", 0.12)])       # new
    audacity_labels.main([str(d), "-o", str(out), "--merge"])
    text = (out / "r1.txt").read_text()
    assert text.startswith(reviewed)
    assert text[len(reviewed):] == "90.000000\t93.000000\t? Blue Grosbeak 0.12\n"
    backups = list(out.glob(".backup-*/r1.txt"))
    assert len(backups) == 1 and backups[0].read_text() == reviewed
    audacity_labels.main([str(d), "-o", str(out), "--merge"])          # idempotent
    assert (out / "r1.txt").read_text() == text
