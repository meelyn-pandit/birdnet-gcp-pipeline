# BirdNET Acoustic Embedding Pipeline on GCP

A portfolio project that runs BirdNET over field recordings, stores detections
and embeddings in BigQuery, and builds toward a few-shot classifier and a
dashboard on top of them.

## Target architecture

```
Hard drive ──rsync──▶ Cloud Storage (raw/)
                          │
          ┌───────────────┴────────────────┐
          ▼                                ▼
  Backfill: Cloud Run Job          Live: Pub/Sub on upload
  (batch over the archive)         ──▶ Cloud Run service
          │                                │
          └───────────────┬────────────────┘
                          ▼
                 BigQuery dataset
       recordings │ detections │ embeddings
                          │
                          ▼
     Few-shot classifier  +  vector search  +  dashboard
```

## Why GCP and BigQuery

- BirdNET is a lightweight TFLite model that runs on CPU, so either cloud
  handles inference equally well.
- BigQuery has built-in vector search, so similarity queries over embeddings
  ("find clips that sound like this one") run in SQL next to detections and
  site metadata.
- BigQuery GIS handles joins to locations and habitat layers without a
  separate geospatial stack.
- Keep the inference step a plain Docker container (read audio from a bucket,
  write results out, no cloud-specific code inside) so the compute can be
  ported to AWS later if needed.

## Repository layout

| Path | What it is |
|---|---|
| `docs/GETTING_STARTED.md` | The five setup phases, in order |
| `docs/ROADMAP.md` | What comes after the data is in the cloud |
| `config/sites_template.csv` | Site metadata to fill in (ID, lat/lon, recorder, time zone) |
| `config/project.env.template` | Project, bucket, region and dataset names |
| `scripts/build_metadata.py` | Walks the drive and builds `metadata.csv`, one row per file |
| `scripts/pick_sample.py` | Copies a stratified sample of files for the local BirdNET test |
| `scripts/estimate_upload.py` | Totals archive size and estimates upload time |
| `scripts/convert_to_flac.py` | Optional lossless WAV → FLAC conversion |
| `scripts/gcp_setup.sh` | Enables APIs, creates the bucket and BigQuery dataset |
| `scripts/upload.sh` | Resumable upload with `gcloud storage rsync` |
| `scripts/load_metadata.sh` | Loads `metadata.csv` into BigQuery |
| `sql/recordings_schema.json` | BigQuery schema for the recordings table |
| `requirements.txt` | Python dependencies for the local scripts |

## Quick start

```bash
pip install -r requirements.txt
cp config/project.env.template config/project.env    # then edit it
# fill in config/sites_template.csv → save as config/sites.csv

python scripts/estimate_upload.py /path/to/recordings --mbps 50
python scripts/build_metadata.py /path/to/recordings --sites config/sites.csv -o metadata.csv
python scripts/pick_sample.py metadata.csv /path/to/recordings sample/ --per-site 3

# test BirdNET locally on sample/ (see docs/GETTING_STARTED.md, phase 2)

bash scripts/gcp_setup.sh
bash scripts/upload.sh /path/to/recordings/site_folder [more site folders ...]
bash scripts/load_metadata.sh metadata.csv
```

## Licensing note

The BirdNET model weights have been released under a non-commercial license
(CC BY-NC-SA). That is fine for a personal portfolio project. If this work
ever becomes part of commercial or employer work, confirm the current license
first, or swap in Google's Perch model, which is released under a more
permissive license.

## Secret scanning

Commits are checked for tokens, keys, passwords, `.env` files and GCP billing
account IDs at three levels:

- **GitHub push protection** rejects pushes containing known token formats
  (enabled in the repo settings).
- **Pre-push hook** runs [gitleaks](https://github.com/gitleaks/gitleaks) with
  the rules in `.gitleaks.toml` and blocks the push locally. Enable it once
  per clone (requires gitleaks on your PATH):
  ```bash
  git config core.hooksPath .githooks
  ```
- **CI** (`.github/workflows/secret-scan.yml`) runs the same scan on every
  push and pull request and fails the check if anything is found.
