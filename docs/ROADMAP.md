# Roadmap

## Stage 1: Data in the cloud — done (aru01 sample)

Metadata table, local BirdNET validation, bucket, upload of the sample,
`recordings` table in BigQuery. Remaining: upload the full archive.

## Stage 2: Containerize inference

- Wrap the detectors (BirdNET and Perch) in a Docker image: read audio from
  a bucket path, write detections and embeddings out. No cloud-specific code
  inside the container, so it stays portable.
- Push to Artifact Registry.
- Run the archive backfill as a Cloud Run Job, chunked by site and date.

## Stage 3: BigQuery tables

- `detections`: recording ID, window offsets, species, score, method
  (BirdNET / Perch / classifier).
- `embeddings`: recording ID, window offsets, embedding vector
  (ARRAY<FLOAT64>). Perch embeddings performed best so far.
- Add a vector index and try similarity queries with `VECTOR_SEARCH`.
- Use BigQuery GIS to join detections to site locations and habitat layers.
- Summaries of vocal activity per species by date and time of day.

## Stage 4: Live ingestion

- Pub/Sub notification on new uploads under `raw/`.
- Cloud Run service processes one file per message.

## Stage 5: Species classifiers — first one done

- Field Sparrow: classifier on Perch v2 embeddings, trained on reviewed
  recordings. Held-out test: 17/23 song windows found, 4 false alarms
  (BirdNET: 3/23). `bgp-evaluate --species "Field Sparrow"`.
- Next: run it across the archive and spot-check ~30 detections by ear;
  add species BirdNET handles poorly (Lark Sparrow) and the unidentified
  calls (2.3 kHz whistle series, 3 kHz trill), which can be tracked unnamed.
- Investigate BirdNET's systematic Yellow-billed Cuckoo false positives at
  this site (22/22 wrong in reviewed files).
- Later: song-level counting (onsets within detected windows) on top of
  window-level detection.

## Stage 6: Dashboard and write-up

- Dashboard: detections over time and space.
- Public write-up (blog post or WILDLABS thread) with the GitHub repo.
