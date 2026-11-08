# BirdNET Acoustic Monitoring Pipeline on GCP

Runs pretrained bird-sound models (BirdNET, Google's Perch) over field
recordings, keeps recording metadata and results in BigQuery, and trains
small species classifiers from your own labels where the pretrained models
fall short.

**First result:** on held-out recordings from central Oklahoma, BirdNET
found 3 of 23 Field Sparrow song windows; a classifier on Perch embeddings
trained on ~60 labeled windows found 17 with 4 false alarms
(`bgp-evaluate --species "Field Sparrow"`).

## Target architecture

```text
Hard drive ──rsync──▶ Cloud Storage (raw/<site>/)
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
     Species classifiers  +  vector search  +  dashboard
```

## Repository layout

```text
├── pyproject.toml          package, dependencies, bgp-* commands
├── requirements.lock       exact versions of the working environment
├── src/birdnet_pipeline/   the code (one copy of each piece of logic)
│   ├── annotations.py      label formats + label-to-window rules (shared by everything)
│   ├── metadata.py         per-recording metadata (site, UTC start, BirdNET week)
│   ├── detectors/          BirdNET output reader, Perch runner (cached)
│   ├── classifier.py       species classifiers on embeddings, save/load
│   ├── evaluation.py       detection metrics, split handling
│   ├── config.py, paths.py species settings, default locations
│   └── cli/                the bgp-* commands
├── tests/                  pytest: label rules, merge safety, metadata
├── configs/                project.env / sites.csv templates, species.toml
├── data/                   local research data, not committed (see data/README.md)
├── models/                 trained classifiers, not committed
├── reports/                evaluation results (JSON), not committed
├── infra/
│   ├── gcp/                setup, upload, BigQuery load scripts
│   └── budget_killswitch/  Cloud Function enforcing the $10/month cap
├── sql/                    BigQuery schemas
└── docs/                   GETTING_STARTED (step by step), ROADMAP
```

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.lock && pip install --no-deps -e .   # exact environment
# or, resolving fresh:  pip install -e ".[ml,dev]"

cp configs/project.env.template configs/project.env    # then edit
cp configs/sites_template.csv configs/sites.csv        # one row per site
pytest                                                 # quick check
```

## Commands

| Command | What it does |
| --- | --- |
| `bgp-estimate-upload DIR` | Total archive size and upload time |
| `bgp-build-metadata DIR` | One row per recording → `data/processed/metadata.csv` |
| `bgp-pick-sample DIR --per-site N` | Copy a sample → `data/raw/sample/` |
| `bgp-convert-flac SRC DST` | Lossless WAV → FLAC |
| `bgp-audacity-labels [--merge]` | BirdNET detections → Audacity label files for review |
| `bgp-review-sheet` | BirdNET detections → review CSV (spreadsheet alternative) |
| `bgp-load-labels` | Your labels → embeddings database |
| `bgp-evaluate --species "..." [--save M]` | BirdNET vs Perch vs classifier on the test split; saves report (and model) |
| `bash infra/gcp/gcp_setup.sh` | Enable APIs, create bucket + BigQuery dataset |
| `bash infra/gcp/upload.sh SITE_DIR...` | Resumable upload to `gs://BUCKET/raw/<site>/` |
| `bash infra/gcp/load_metadata.sh` | Load the metadata table into BigQuery |
| `bash infra/gcp/setup_github_wif.sh` | One-time: let the GitHub `deploy` workflow deploy the detection job via Workload Identity Federation (no keys) |

Every command has `--help`. Defaults point into `data/`, `models/` and
`reports/`; pass paths to override. The full workflow is in
[docs/GETTING_STARTED.md](docs/GETTING_STARTED.md).

## Licensing note

The BirdNET model weights are released under a non-commercial license
(CC BY-NC-SA), fine for a personal portfolio project. For commercial or
employer work, confirm the current license first. Perch is released under a
more permissive license.

## Secret scanning

Commits are checked for tokens, keys, passwords, `.env` files and GCP billing
account IDs at three levels:

- **GitHub push protection** rejects pushes containing known token formats.
- **Pre-push hook** runs [gitleaks](https://github.com/gitleaks/gitleaks) with
  the rules in `.gitleaks.toml` and blocks the push locally. Enable it once
  per clone (requires gitleaks on your PATH):
  ```bash
  git config core.hooksPath .githooks
  ```
- **CI** (`.github/workflows/secret-scan.yml`) runs the same scan on every
  push and pull request.
