# Getting Started

Six phases, in order. Nothing touches the cloud until phase 3. Setup of the
Python environment is in the [README](../README.md#setup); every command
below has `--help`.

---

## Phase 1: Inventory the recordings and build a metadata table

Find out what is on the drive: file format, sample rate, total size, and how
files are named and organized into folders.

```bash
bgp-estimate-upload /path/to/recordings --mbps 50
```

Then build the metadata table, one row per file: relative path, site ID,
latitude, longitude, recorder model, start time (UTC), duration, sample rate,
channels.

1. Copy `configs/sites_template.csv` to `configs/sites.csv` and fill in one
   row per site.
2. Run (writes `data/processed/metadata.csv`):

   ```bash
   bgp-build-metadata /path/to/recordings
   ```

The site ID comes from the file's parent folder name and timestamps like
`20240512_053000` are parsed from the filename (AudioMoth / Song Meter style).
`rel_path` always starts with the site folder (`aru01/20240512_053000.WAV`),
so sites that share timestamp filenames never collide.

**Time zones:** check the recorder's settings. AudioMoth writes filenames in
the time zone it was configured with (see `CONFIG.TXT` or the WAV comment,
e.g. "Recorded at 05:00:00 23/05/2021 (UTC-5)"). A fixed offset is written
`Etc/GMT+5` for UTC-5 (the sign is reversed in that naming scheme).

---

## Phase 2: Run BirdNET locally on a small sample

Copy 10 to 20 files from different sites and conditions into `data/raw/sample/`:

```bash
bgp-pick-sample /path/to/recordings --per-site 3
```

Run BirdNET for detections and embeddings:

```bash
python -m birdnet_analyzer.analyze data/raw/sample -o data/interim/birdnet \
    --lat <recorder lat> --lon <recorder lon> --week -1 \
    --overlap 2 --min_conf 0.1 --rtype table
python -m birdnet_analyzer.embeddings -i data/raw/sample -db ./data/processed/embeddings_db
```

Things learned the hard way:

- **`--lat/--lon` are where the recorder was**, not where you are. They are
  the values in `configs/sites.csv`. BirdNET does not read that file; you
  must pass them.
- **The location filter removes every non-bird.** With `--lat/--lon`, BirdNET
  keeps only birds expected at that place and week, so frogs and insects
  are never reported. Run without them (or use Perch) when non-birds matter.
- **`--overlap 2`** scores a window every second, so songs split by the
  default 3 s grid are not missed. **`--min_conf 0.1`** keeps faint songs
  that the default 0.25 drops.
- Give `-db` a path containing a folder (`./data/...`). With a bare name,
  birdnet-analyzer 2.4.0 crashes in a worker process and hangs after
  "Files processed: 100%".

**License check:** see the note in the README before using BirdNET beyond
personal work.

---

## Phase 3: Set up the GCP project

1. Create a dedicated project and a budget immediately (this project uses a
   $10/month hard cap: see `infra/budget_killswitch/README.md`).
2. Copy `configs/project.env.template` to `configs/project.env` and fill it in.
3. Run:

   ```bash
   bash infra/gcp/gcp_setup.sh
   ```

This enables Cloud Storage, Cloud Run, Pub/Sub, BigQuery and Artifact
Registry, and creates the bucket and BigQuery dataset in the **same region**.
Same-region placement avoids cross-region transfer costs and query
restrictions.

---

## Phase 4: Upload and load the metadata table

Upload each site folder to `gs://BUCKET/raw/<site>/` (resumable; rerun to
continue). Point it at site folders only, so other material on the drive
(e.g. extracted clips) stays out of the bucket:

```bash
bash infra/gcp/upload.sh /path/to/recordings/aru01 [/path/to/aru02 ...]
bash infra/gcp/load_metadata.sh          # data/processed/metadata.csv -> BigQuery
```

**Optional FLAC conversion** (lossless, roughly half the size; BirdNET and
Perch read FLAC). Build metadata from the original WAVs first if you need
the AudioMoth comment chunk, which FLAC drops:

```bash
bgp-convert-flac /path/to/recordings /path/to/flac_copy
```

---

## Phase 5: Label, train and evaluate species detectors

Pretrained models miss species at some sites (here BirdNET found 3 of 23
Field Sparrow windows). Your labels fix that.

1. **Make review files** from BirdNET's detections, one Audacity label file
   per recording in `data/annotations/labels/`:

   ```bash
   bgp-audacity-labels            # after re-running BirdNET later: --merge
   ```

2. **Review in Audacity**: open the WAV, *File > Import > Labels* the
   matching `.txt`, then edit label text:

   | Label | Meaning |
   | --- | --- |
   | `? Indigo Bunting 0.43` | unreviewed (ignored) |
   | `Indigo Bunting 0.43` | confirmed: delete the `?` |
   | `- Indigo Bunting 0.43` | wrong: change `?` to `-` (don't delete it) |
   | `Northern Bobwhite` | a call BirdNET missed (Ctrl+B to add) |
   | `? unknown 2.3 kHz` | heard but unsure (excluded from training) |

   Export the labels back to the same file. For a species you want a
   detector for, **label every song** in the recordings you review: unlabeled
   windows count as "absent".

3. **Split** reviewed recordings into train and test in
   `data/splits/split.csv` (`recording,split`). Never tune anything on test.

4. **Evaluate and save** (BirdNET vs Perch vs a classifier on Perch
   embeddings; results go to `reports/`):

   ```bash
   bgp-evaluate --species "Field Sparrow" --save models/field_sparrow_perch.joblib
   ```

   Add a species to `configs/species.toml` (common + Perch scientific name).

5. Optionally load labels into the embeddings database: `bgp-load-labels`.

**Back up `data/annotations/`**: it is the one thing you cannot regenerate.

---

## Phase 6: Keep the backfill and live ingestion separate

- **Existing archive:** process as a batch with a Cloud Run Job that walks the
  bucket in chunks.
- **New recordings going forward:** Pub/Sub notification on upload triggers a
  Cloud Run service.

Do **not** wire up the Pub/Sub trigger before the bulk upload: it fires one
event per file and spins up thousands of tiny invocations.

---

## Checklist

- [ ] Archive size and format known (`bgp-estimate-upload`)
- [ ] `configs/sites.csv` filled in, time zones confirmed
- [ ] Metadata table built and spot-checked
- [ ] BirdNET run on a sample with the recorders' coordinates
- [ ] GCP project with a budget cap; bucket and dataset in one region
- [ ] Recordings uploaded; `recordings` table in BigQuery
- [ ] Review files labeled; train/test split defined
- [ ] Species detector evaluated on the test split
