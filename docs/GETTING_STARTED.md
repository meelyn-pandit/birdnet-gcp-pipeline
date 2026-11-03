# Getting Started

Five phases, in order. Nothing touches the cloud until phase 3.

---

## Phase 1: Inventory the recordings and build a metadata table

Find out what is on the drive: file format, sample rate, total size, and how
files are named and organized into folders.

```bash
python scripts/estimate_upload.py /path/to/recordings --mbps 50
```

Then build `metadata.csv`, one row per file, with: relative path, site ID,
latitude, longitude, recorder model, start timestamp (UTC), duration, sample
rate, and channels.

1. Copy `config/sites_template.csv` to `config/sites.csv` and fill in one row
   per site.
2. Run:

   ```bash
   python scripts/build_metadata.py /path/to/recordings \
       --sites config/sites.csv -o metadata.csv
   ```

By default the script takes the site ID from the file's parent folder name and
parses timestamps like `20240512_053000` from the filename (AudioMoth and Song
Meter style). See `--help` for the options to change both.

**Why this matters:** BirdNET uses location and week of year to filter out
species that should not be present, which noticeably improves results. This
CSV also becomes the first BigQuery table, the one every detection and
embedding joins back to.

**Time zones:** AudioMoth recorders usually write filenames in UTC; others
use local time. The `timezone` column in `sites.csv` tells the script how to
interpret each site's filenames. Getting this right now saves a lot of
confusion when you analyse dawn chorus timing later.

---

## Phase 2: Run BirdNET locally on a small sample

Pick 10 to 20 files from different sites and conditions:

```bash
python scripts/pick_sample.py metadata.csv /path/to/recordings sample/ --per-site 3
```

Install BirdNET-Analyzer and run it on the sample. Embeddings need the
`embeddings` extra, and with birdnet-analyzer 2.4.0 you must also pin
`perch-hoplite` below 1.0, because 1.0 renamed a class that 2.4.0 still uses:

```bash
pip install "birdnet-analyzer[embeddings]==2.4.0" "perch-hoplite<1.0"
```

The package has separate entry points for detections and embeddings, roughly:

```bash
python -m birdnet_analyzer.analyze  sample/ -o out/ --lat 39.0 --lon -74.9 --week 20
python -m birdnet_analyzer.embeddings -i sample/ -db ./embeddings_db
```

Give `-db` a path that contains a folder, such as `./embeddings_db`. With a
bare name like `embeddings_db`, 2.4.0 crashes in a worker process and the
command hangs forever after "Files processed: 100%".

Flags change between releases, so check the current BirdNET-Analyzer README
for exact options and supported Python versions.

What to check:

- Every file decodes without errors.
- You understand the output formats for detections and embeddings.
- Detections match what you know is in the recordings. Your own field
  knowledge makes this spot check far stronger than it would be for most
  people, so write down the misses and false positives; they are useful
  material for the few-shot classifier later.

**License check:** see the note in the README before using BirdNET for
anything beyond personal work.

---

## Phase 3: Set up the GCP project

1. Create a dedicated project.
2. Set a billing budget alert immediately (`scripts/gcp_setup.sh` has the
   command, commented out, since it needs your billing account ID).
3. Copy `config/project.env.template` to `config/project.env` and fill it in.
4. Run:

   ```bash
   bash scripts/gcp_setup.sh
   ```

This enables Cloud Storage, Cloud Run, Pub/Sub, BigQuery and Artifact
Registry, and creates the bucket and BigQuery dataset in the **same region**
(us-east1 or us-east4 are closest to New Jersey). Same-region placement avoids
cross-region transfer costs and query restrictions.

---

## Phase 4: Upload with a predictable layout

Recommended bucket layout:

```
gs://your-bucket/raw/{site_id}/{YYYY}/{MM}/{DD}/{filename}
```

If the drive is already organized by site, the simplest path is to mirror it:

```bash
bash scripts/upload.sh /path/to/recordings/site_folder [more site folders ...]
```

The script uses `gcloud storage rsync`, so an interrupted transfer can be
rerun and will skip files already uploaded. It also excludes macOS `.DS_Store`
and `._*` files.

**Upload time:** 500 GB over a 50 Mbps upload link takes roughly 22 hours.
`estimate_upload.py` prints the estimate for your archive.

**Optional FLAC conversion:** FLAC is lossless and typically cuts WAV size by
around half. BirdNET reads FLAC fine.

```bash
python scripts/convert_to_flac.py /path/to/recordings /path/to/flac_copy
```

Then upload the FLAC copy and rebuild `metadata.csv` from it.

Finally, load the metadata table:

```bash
bash scripts/load_metadata.sh metadata.csv
```

---

## Phase 5: Keep the backfill and live ingestion separate

- **Existing archive:** process as a batch with a Cloud Run Job that walks the
  bucket in chunks.
- **New recordings going forward:** Pub/Sub notification on upload triggers a
  Cloud Run service.

Do **not** wire up the Pub/Sub trigger before the bulk upload. Doing so fires
one event per file and spins up thousands of tiny invocations, which is slower
and messier than a single batch job.

---

## Checklist

- [ ] `estimate_upload.py` run; archive size and format known
- [ ] `config/sites.csv` filled in, time zones confirmed
- [ ] `metadata.csv` built and spot-checked
- [ ] BirdNET run locally on a sample; detections validated by ear
- [ ] BirdNET license confirmed for intended use
- [ ] GCP project created with a budget alert
- [ ] Bucket and BigQuery dataset created in the same region
- [ ] Recordings uploaded (FLAC conversion decided)
- [ ] `recordings` table loaded into BigQuery
