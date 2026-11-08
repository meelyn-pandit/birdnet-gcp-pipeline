#!/usr/bin/env bash
# Load all detection CSVs written by the job into $DATASET.detections (replaces the table).
# Usage: bash infra/gcp/load_detections.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
source configs/project.env

bq --project_id="$PROJECT_ID" load --replace \
  --source_format=CSV --skip_leading_rows=1 \
  "$PROJECT_ID:$DATASET.detections" \
  "gs://$BUCKET/derived/detections/*" \
  sql/detections_schema.json

bq --project_id="$PROJECT_ID" query --use_legacy_sql=false \
  "SELECT method, COUNT(DISTINCT recording_id) AS recordings, COUNT(*) AS rows_,
          COUNT(DISTINCT species_scientific) AS species
   FROM \`$PROJECT_ID.$DATASET.detections\` GROUP BY method ORDER BY method"
