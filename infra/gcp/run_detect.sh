#!/usr/bin/env bash
# Execute the detection Cloud Run Job and wait for it to finish.
# Recordings that already have output are skipped, so re-running resumes.
#
# Usage: bash infra/gcp/run_detect.sh            # all recordings
#        bash infra/gcp/run_detect.sh --limit 2  # each task does at most 2 (smoke test)
set -euo pipefail
cd "$(dirname "$0")/../.."
source configs/project.env

EXTRA=""
if [ "${1:-}" = "--limit" ]; then
  EXTRA=",--limit=${2:?--limit needs a number}"
fi
gcloud --project="$PROJECT_ID" run jobs execute detect --region="$REGION" --wait \
  ${EXTRA:+--args="--metadata=gs://$BUCKET/metadata/recordings.csv,--audio=gs://$BUCKET/$RAW_PREFIX,--out=gs://$BUCKET/derived,--threads=4$EXTRA"}

echo "Outputs:"
gcloud storage du -s "gs://$BUCKET/derived/detections/" "gs://$BUCKET/derived/embeddings/" 2>/dev/null || true
echo "Load into BigQuery with: bash infra/gcp/load_detections.sh"
