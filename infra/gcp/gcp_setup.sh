#!/usr/bin/env bash
# One-time GCP setup: enable APIs, create the bucket and BigQuery dataset
# in the same region. Reads configs/project.env.
set -euo pipefail
cd "$(dirname "$0")/../.."
source configs/project.env

gcloud config set project "$PROJECT_ID"

gcloud services enable \
  storage.googleapis.com \
  run.googleapis.com \
  pubsub.googleapis.com \
  bigquery.googleapis.com \
  artifactregistry.googleapis.com

if ! gcloud storage buckets describe "gs://$BUCKET" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://$BUCKET" \
    --location="$REGION" \
    --uniform-bucket-level-access
else
  echo "Bucket gs://$BUCKET already exists"
fi

if ! bq show "$PROJECT_ID:$DATASET" >/dev/null 2>&1; then
  bq --location="$REGION" mk --dataset "$PROJECT_ID:$DATASET"
else
  echo "Dataset $DATASET already exists"
fi

# Budget alert: do this first. Needs your billing account ID
# (gcloud billing accounts list) and the billingbudgets API enabled.
# gcloud services enable billingbudgets.googleapis.com
# gcloud billing budgets create \
#   --billing-account=XXXXXX-XXXXXX-XXXXXX \
#   --display-name="birdnet-pipeline" \
#   --budget-amount=50USD \
#   --threshold-rule=percent=0.5 \
#   --threshold-rule=percent=0.9 \
#   --threshold-rule=percent=1.0

echo "Setup complete: gs://$BUCKET and $PROJECT_ID:$DATASET in $REGION"
