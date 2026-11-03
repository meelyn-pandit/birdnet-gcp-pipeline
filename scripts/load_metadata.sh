#!/usr/bin/env bash
# Load metadata.csv into $DATASET.recordings (replaces the table).
# Usage: bash scripts/load_metadata.sh metadata.csv
set -euo pipefail
cd "$(dirname "$0")/.."
source config/project.env

CSV="${1:-metadata.csv}"

bq load --replace \
  --source_format=CSV \
  --skip_leading_rows=1 \
  "$PROJECT_ID:$DATASET.recordings" \
  "$CSV" \
  sql/recordings_schema.json

bq query --use_legacy_sql=false \
  "SELECT site_id, COUNT(*) AS files, ROUND(SUM(duration_s)/3600, 1) AS hours,
          COUNTIF(error != '') AS errors
   FROM \`$PROJECT_ID.$DATASET.recordings\`
   GROUP BY site_id ORDER BY site_id"
