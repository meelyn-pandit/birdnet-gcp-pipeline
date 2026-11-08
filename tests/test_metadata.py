from datetime import datetime

import numpy as np
import soundfile as sf

from birdnet_pipeline.metadata import birdnet_week, load_sites, metadata_row


def test_birdnet_week():
    assert birdnet_week(datetime(2021, 5, 23)) == 20
    assert birdnet_week(datetime(2021, 8, 14)) == 30
    assert birdnet_week(datetime(2021, 1, 1)) == 1
    assert birdnet_week(datetime(2021, 12, 31)) == 48


def test_metadata_row_site_prefix_and_utc(tmp_path):
    site = tmp_path / "aru01"
    site.mkdir()
    wav = site / "20210523_050000.WAV"
    sf.write(wav, np.zeros(48000, dtype="int16"), 48000, subtype="PCM_16")
    sites_csv = tmp_path / "sites.csv"
    sites_csv.write_text("site_id,latitude,longitude,recorder,timezone,notes\n"
                         "aru01,35.061841,-97.193914,AudioMoth,Etc/GMT+5,\n")
    for root in (site, tmp_path):            # site folder itself, or the folder above it
        row = metadata_row(wav.resolve(), load_sites(sites_csv))
        assert row["rel_path"] == "aru01/20210523_050000.WAV"
        assert row["site_id"] == "aru01"
        assert row["start_utc"] == "2021-05-23 10:00:00 UTC"     # fixed UTC-5 local time
        assert row["birdnet_week"] == 20
        assert row["duration_s"] == 1.0 and row["sample_rate"] == 48000
        assert row["latitude"] == "35.061841" and row["error"] == ""
