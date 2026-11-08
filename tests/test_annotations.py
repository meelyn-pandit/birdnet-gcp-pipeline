import numpy as np
import pytest

from birdnet_pipeline.annotations import (NEG, POS, UNSURE, grid_windows, ground_truth, parse_label_text,
                                          read_audacity, read_review_csv, stem, window_hits)


@pytest.mark.parametrize("text,expected", [
    ("? Field Sparrow 0.25", ("Field Sparrow", UNSURE)),
    ("Field Sparrow 0.25", ("Field Sparrow", POS)),       # "?" deleted, score left in
    ("Field Sparrow", ("Field Sparrow", POS)),
    ("- Field Sparrow 0.25", ("Field Sparrow", NEG)),
    ("-Field Sparrow", ("Field Sparrow", NEG)),
    ("neg Indigo Bunting 0.43", ("Indigo Bunting", NEG)),
    ("not Indigo Bunting", ("Indigo Bunting", NEG)),
    (" Northern Bobwhite ", ("Northern Bobwhite", POS)),
    ("Field Sparrow 1.0", ("Field Sparrow", POS)),
    ("? unknown 2.3 kHz", ("unknown 2.3 kHz", UNSURE)),   # "2.3" is not a 0-1 score
    ("", ("", UNSURE)),
])
def test_parse_label_text(text, expected):
    assert parse_label_text(text) == expected


def test_stem():
    assert stem("data/raw/sample/20210524_053000.WAV") == "20210524_053000"
    assert stem("20210524_053000.BirdNET.selection.table.txt") == "20210524_053000"


def test_read_audacity_skips_spectral_lines_and_handles_crlf(tmp_path):
    p = tmp_path / "20210524_071000.txt"
    p.write_bytes(b"18.0\t21.0\tField Sparrow\r\n\\\t2000.0\t8000.0\r\n"
                  b"69.0\t72.0\t- Prairie Warbler\r\n108.0\t111.0\t? Prairie Warbler 0.28\r\n")
    anns = read_audacity(p, "me")
    assert [(a.recording, a.label, a.kind) for a in anns] == [
        ("20210524_071000", "Field Sparrow", POS),
        ("20210524_071000", "Prairie Warbler", NEG),
        ("20210524_071000", "Prairie Warbler", UNSURE)]
    assert anns[0].provenance == "me"


def test_read_audacity_rejects_malformed(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("18.0 21.0 Field Sparrow\n")
    with pytest.raises(ValueError, match="x.txt:1"):
        read_audacity(p)


def test_review_csv_blank_type_is_unsure(tmp_path):
    p = tmp_path / "review.csv"
    p.write_text("file,start_s,end_s,label,confidence,type,notes\n"
                 "20210524_071000.WAV,18,21,Field Sparrow,0.25,pos,\n"
                 "20210524_071000.WAV,69,72,Prairie Warbler,0.40,,\n")
    kinds = [(a.recording, a.kind) for a in read_review_csv(p)]
    assert kinds == [("20210524_071000", POS), ("20210524_071000", UNSURE)]


W = grid_windows(40)


def test_window_hits_overlap_rule():
    assert window_hits(104.5, 110.0, W) == [34, 35, 36]       # 102-105 (0.5 s), 105-108, 108-111
    assert window_hits(2.8, 3.2, W) == [0, 1]                  # 0.4 s call: half-length rule
    assert window_hits(40.25, 40.25, W) == [13]                # point label -> 39-42


def test_window_hits_short_calls():
    # Real cases that the old fixed 0.5 s rule dropped entirely:
    assert window_hits(93.94, 94.30, W) == [31]                # 0.36 s note inside 93-96
    # 0.83 s crow call across the 102 s boundary needs 0.414 s: 99-102 gets 0.393 (no), 102-105 0.435 (yes)
    assert window_hits(101.607, 102.435, W) == [34]


def test_ground_truth_pos_neg_unsure():
    from birdnet_pipeline.annotations import Annotation as A
    anns = [A("r", 18, 21, "Field Sparrow", POS),
            A("r", 18, 21, "Field Sparrow", NEG),              # positive wins
            A("r", 30, 33, "Field Sparrow", UNSURE),           # excluded
            A("r", 60, 63, "Field Sparrow", NEG),              # negative = absent
            A("r", 90, 93, "Indigo Bunting", POS)]             # other species ignored
    y = ground_truth(anns, "field sparrow", W)
    assert y[6] == 1 and y[10] == -1 and y[20] == 0 and y[30] == 0
    assert (y == 1).sum() == 1 and (y == -1).sum() == 1
