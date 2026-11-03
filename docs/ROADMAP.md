# Roadmap

## Stage 1: Data in the cloud (docs/GETTING_STARTED.md)
Metadata table, local BirdNET validation, bucket, upload, recordings table.

## Stage 2: Containerize inference
- Wrap BirdNET in a Docker image: read audio from a bucket path, write
  detections and embeddings out. No cloud-specific code inside the
  container, so it stays portable.
- Push to Artifact Registry.
- Run the archive backfill as a Cloud Run Job, chunked by site and date.

## Stage 3: BigQuery tables
- `detections`: recording ID, start and end offsets, species, confidence.
- `embeddings`: recording ID, segment offsets, embedding vector
  (ARRAY<FLOAT64>).
- Add a vector index and try similarity queries with `VECTOR_SEARCH`.
- Use BigQuery GIS to join detections to site locations and habitat layers.

## Stage 4: Live ingestion
- Pub/Sub notification on new uploads under `raw/`.
- Cloud Run service processes one file per message.

## Stage 5: Few-shot classifier
- Pick a species or call type you know well, especially one BirdNET handles
  poorly (the misses noted in phase 2).
- Label a small set of embedding segments; train a lightweight classifier
  (logistic regression or a small MLP) on the embeddings.
- Write predictions back to BigQuery.

## Stage 6: Dashboard and write-up
- Flutter or simple web dashboard: detections over time and space.
- Public write-up (blog post or WILDLABS thread) with the GitHub repo.
