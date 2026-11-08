#!/usr/bin/env bash
# Build the detection image in Cloud Build and create/update the Cloud Run Job.
# Idempotent: safe to re-run after code changes (new image tag = git commit).
#
# Creates (if missing): Artifact Registry repo, a service account that can only
# read/write this project's bucket, then uploads the metadata table and
# classifier bundles the job reads, builds the image, and deploys the job.
#
# Usage: bash infra/gcp/deploy_detect.sh [--code-only] [TASKS] [PARALLELISM]
#
# --code-only: skip the one-time setup and the input uploads; only build the
# image and update the job. This is what CI runs (.github/workflows/deploy.yml),
# because the runner has no data/ or models/ and its service account cannot
# create service accounts or change IAM. Source and build logs are staged in
# the CI bucket made by infra/gcp/setup_github_wif.sh.
set -euo pipefail
cd "$(dirname "$0")/../.."
source configs/project.env

CODE_ONLY=0
if [ "${1:-}" = "--code-only" ]; then CODE_ONLY=1; shift; fi
TASKS="${1:-20}"
PARALLELISM="${2:-5}"
CI_BUCKET="${CI_BUCKET:-$PROJECT_ID-ci-builds}"
REPO="birdnet"
JOB="detect"
SA_NAME="detect-runner"
SA="$SA_NAME@$PROJECT_ID.iam.gserviceaccount.com"
TAG="$(git rev-parse --short HEAD)$(git diff --quiet HEAD -- src Dockerfile requirements.lock || echo -dirty)"
IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/$JOB:$TAG"
G="gcloud --project=$PROJECT_ID"

if [ "$CODE_ONLY" = 0 ]; then
  echo "== Artifact Registry repo"
  $G artifacts repositories describe "$REPO" --location="$REGION" >/dev/null 2>&1 || \
    $G artifacts repositories create "$REPO" --location="$REGION" --repository-format=docker \
       --description="BirdNET pipeline images"

  echo "== Service account $SA (bucket access only)"
  $G iam service-accounts describe "$SA" >/dev/null 2>&1 || \
    $G iam service-accounts create "$SA_NAME" --display-name="Detection job runner"
  # A new service account can take a few seconds to become visible to IAM.
  for i in 1 2 3 4 5 6; do
    if gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" \
         --member="serviceAccount:$SA" --role="roles/storage.objectAdmin" >/dev/null 2>&1; then
      break
    fi
    [ "$i" = 6 ] && { echo "Could not grant bucket access to $SA" >&2; exit 1; }
    echo "  service account not visible yet; retrying in 10 s"; sleep 10
  done

  echo "== Inputs the job reads from the bucket"
  gcloud storage cp data/processed/metadata.csv "gs://$BUCKET/metadata/recordings.csv"
  for m in models/*.joblib; do gcloud storage cp "$m" "gs://$BUCKET/models/"; done
fi

echo "== Build $IMAGE (Cloud Build)"
BUILD_FLAGS=()
if [ "$CODE_ONLY" = 1 ]; then
  BUILD_FLAGS=(--gcs-source-staging-dir="gs://$CI_BUCKET/source"
               --gcs-log-dir="gs://$CI_BUCKET/logs")
fi
$G builds submit --tag "$IMAGE" --region="$REGION" --timeout=45m "${BUILD_FLAGS[@]}" .

echo "== Deploy Cloud Run Job $JOB ($TASKS tasks, $PARALLELISM at a time)"
$G run jobs deploy "$JOB" --region="$REGION" --image="$IMAGE" \
  --service-account="$SA" --tasks="$TASKS" --parallelism="$PARALLELISM" \
  --cpu=4 --memory=8Gi --task-timeout=60m --max-retries=1 \
  --args="--metadata=gs://$BUCKET/metadata/recordings.csv,--audio=gs://$BUCKET/$RAW_PREFIX,--out=gs://$BUCKET/derived,--threads=4"

echo "Deployed. Run it with: bash infra/gcp/run_detect.sh"
