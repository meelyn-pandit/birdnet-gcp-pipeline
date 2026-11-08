# data/

Everything in here is local research data and is not committed (see
`.gitignore`). Only this README is tracked. Default paths used by the
`bgp-*` commands are defined in `src/birdnet_pipeline/paths.py`.

| Folder | Contents | Made by |
|---|---|---|
| `raw/sample/` | Recordings used for development (copied from the field drive) | `bgp-pick-sample` |
| `raw/sample_flac/` | FLAC copies of the sample | `bgp-convert-flac` |
| `raw/aru_locations_*.csv` | Recorder coordinates (sensitive: never commit) | you |
| `annotations/labels/` | Audacity label files, one per recording: **your review work** | `bgp-audacity-labels`, then you |
| `annotations/review.csv` | Spreadsheet-style review sheet (alternative to Audacity) | `bgp-review-sheet` |
| `interim/birdnet/` | BirdNET selection tables (re-creatable) | `birdnet_analyzer.analyze` |
| `interim/perch_cache/` | Cached Perch scores and embeddings (re-creatable) | `bgp-evaluate` |
| `processed/metadata.csv` | One row per recording: site, UTC start, duration... | `bgp-build-metadata` |
| `processed/embeddings_db/` | BirdNET embeddings + your labels (Perch Hoplite DB) | `birdnet_analyzer.embeddings`, `bgp-load-labels` |
| `splits/split.csv` | Which recordings are train / test | you |

**Back up `annotations/`.** Everything else can be regenerated; your labels
cannot. For example:

```bash
gcloud storage rsync -r data/annotations/ gs://birdnet-pipeline-birdnet-audio/annotations/
```
