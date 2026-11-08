#!/usr/bin/env bash
# Resumable upload of one or more site folders to gs://$BUCKET/$RAW_PREFIX/<site>/.
# Each folder's name becomes its prefix in the bucket, matching rel_path in
# metadata.csv (e.g. aru01/20210523_050000.WAV). Rerunning skips files that
# are already uploaded.
# Usage: bash infra/gcp/upload.sh /path/to/aru01 [/path/to/aru02 ...]
#        bash infra/gcp/upload.sh /path/to/lwma_audio_files/aru*
set -euo pipefail
SRC_DIRS=()
for d in "$@"; do SRC_DIRS+=("$(cd "$d" && pwd)"); done
cd "$(dirname "$0")/../.."
source configs/project.env

[ ${#SRC_DIRS[@]} -gt 0 ] || { echo "Usage: upload.sh SITE_DIR [SITE_DIR ...]" >&2; exit 1; }

for SRC in "${SRC_DIRS[@]}"; do
  SITE="$(basename "$SRC")"
  echo "Uploading $SRC -> gs://$BUCKET/$RAW_PREFIX/$SITE/"
  gcloud storage rsync -r "$SRC" "gs://$BUCKET/$RAW_PREFIX/$SITE/" \
    --exclude='(^|.*/)(\.DS_Store|\._.*|Thumbs\.db)$'
done
