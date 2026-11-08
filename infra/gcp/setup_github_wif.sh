#!/usr/bin/env bash
# One-time: let GitHub Actions deploy the detection job without a key file.
#
# Sets up Workload Identity Federation: GitHub's short-lived OIDC token for a
# workflow run in this repo, on the trunk branch, is exchanged for a token of
# the gh-deployer service account. No JSON key is ever created.
#
# gh-deployer can only: submit Cloud Build builds (source and logs staged in a
# dedicated CI bucket that deletes objects after 7 days), deploy Cloud Run Jobs,
# and act as the detect-runner and Cloud Build service accounts. It has no
# access to the audio bucket.
#
# Run once after the first local `bash infra/gcp/deploy_detect.sh` (that makes
# the Artifact Registry repo and the detect-runner service account).
# Idempotent: safe to re-run.
#
# Usage: bash infra/gcp/setup_github_wif.sh [OWNER/REPO]
set -euo pipefail
cd "$(dirname "$0")/../.."
source configs/project.env

GH_REPO="${1:-meelyn-pandit/birdnet-gcp-pipeline}"
GH_REF="refs/heads/trunk"
POOL="github"
PROVIDER="github-repo"
DEPLOYER_NAME="gh-deployer"
DEPLOYER="$DEPLOYER_NAME@$PROJECT_ID.iam.gserviceaccount.com"
RUNNER="detect-runner@$PROJECT_ID.iam.gserviceaccount.com"
AR_REPO="birdnet"
CI_BUCKET="${CI_BUCKET:-$PROJECT_ID-ci-builds}"
G="gcloud --project=$PROJECT_ID"
PROJECT_NUMBER="$($G projects describe "$PROJECT_ID" --format='value(projectNumber)')"

echo "== Prerequisites from deploy_detect.sh"
$G iam service-accounts describe "$RUNNER" >/dev/null 2>&1 && \
$G artifacts repositories describe "$AR_REPO" --location="$REGION" >/dev/null 2>&1 || {
  echo "Missing $RUNNER or the '$AR_REPO' Artifact Registry repo." >&2
  echo "Run 'bash infra/gcp/deploy_detect.sh' locally once first." >&2
  exit 1
}

echo "== APIs"
$G services enable iamcredentials.googleapis.com sts.googleapis.com \
  cloudbuild.googleapis.com run.googleapis.com artifactregistry.googleapis.com

echo "== Workload identity pool + GitHub provider (only $GH_REPO @ $GH_REF)"
$G iam workload-identity-pools describe "$POOL" --location=global >/dev/null 2>&1 || \
  $G iam workload-identity-pools create "$POOL" --location=global \
     --display-name="GitHub Actions"
CONDITION="assertion.repository=='$GH_REPO' && assertion.ref=='$GH_REF'"
if $G iam workload-identity-pools providers describe "$PROVIDER" \
     --location=global --workload-identity-pool="$POOL" >/dev/null 2>&1; then
  $G iam workload-identity-pools providers update-oidc "$PROVIDER" \
     --location=global --workload-identity-pool="$POOL" \
     --attribute-condition="$CONDITION" >/dev/null
else
  $G iam workload-identity-pools providers create-oidc "$PROVIDER" \
     --location=global --workload-identity-pool="$POOL" \
     --display-name="GitHub repo $GH_REPO" \
     --issuer-uri="https://token.actions.githubusercontent.com" \
     --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
     --attribute-condition="$CONDITION"
fi
PROVIDER_PATH="projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$POOL/providers/$PROVIDER"

echo "== Deployer service account $DEPLOYER"
$G iam service-accounts describe "$DEPLOYER" >/dev/null 2>&1 || \
  $G iam service-accounts create "$DEPLOYER_NAME" --display-name="GitHub Actions deployer"
# A new service account can take a few seconds to become visible to IAM.
for i in 1 2 3 4 5 6; do
  if $G iam service-accounts add-iam-policy-binding "$DEPLOYER" \
       --role=roles/iam.workloadIdentityUser \
       --member="principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$POOL/attribute.repository/$GH_REPO" \
       >/dev/null 2>&1; then
    break
  fi
  [ "$i" = 6 ] && { echo "Could not bind workload identity to $DEPLOYER" >&2; exit 1; }
  echo "  service account not visible yet; retrying in 10 s"; sleep 10
done

echo "== Project roles for the deployer"
for role in roles/cloudbuild.builds.editor roles/run.developer \
            roles/serviceusage.serviceUsageConsumer; do
  $G projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$DEPLOYER" \
     --role="$role" --condition=None >/dev/null
done

echo "== Service accounts the deployer may act as (not every SA in the project)"
BUILD_SA="$($G builds get-default-service-account --region="$REGION" \
              --format='value(serviceAccountEmail)' 2>/dev/null | sed 's#.*/##')"
BUILD_SA="${BUILD_SA:-$PROJECT_NUMBER-compute@developer.gserviceaccount.com}"
for sa in "$RUNNER" "$BUILD_SA"; do
  $G iam service-accounts add-iam-policy-binding "$sa" \
     --member="serviceAccount:$DEPLOYER" --role=roles/iam.serviceAccountUser >/dev/null
  echo "  $sa"
done

echo "== CI bucket gs://$CI_BUCKET (build source + logs, deleted after 7 days)"
gcloud storage buckets describe "gs://$CI_BUCKET" >/dev/null 2>&1 || \
  gcloud storage buckets create "gs://$CI_BUCKET" --project="$PROJECT_ID" \
     --location="$REGION" --uniform-bucket-level-access
LIFECYCLE="$(mktemp)"; trap 'rm -f "$LIFECYCLE" "${CLEANUP:-}"' EXIT
echo '{"rule":[{"action":{"type":"Delete"},"condition":{"age":7}}]}' > "$LIFECYCLE"
gcloud storage buckets update "gs://$CI_BUCKET" --lifecycle-file="$LIFECYCLE"
for sa in "$DEPLOYER" "$BUILD_SA"; do
  gcloud storage buckets add-iam-policy-binding "gs://$CI_BUCKET" \
     --member="serviceAccount:$sa" --role=roles/storage.objectAdmin >/dev/null
done

echo "== Artifact Registry cleanup: keep the 5 newest images, drop the rest after 30 days"
CLEANUP="$(mktemp)"
cat > "$CLEANUP" <<'JSON'
[
  {"name": "keep-newest-5", "action": {"type": "Keep"},
   "mostRecentVersions": {"keepCount": 5}},
  {"name": "delete-older-than-30d", "action": {"type": "Delete"},
   "condition": {"tagState": "any", "olderThan": "30d"}}
]
JSON
$G artifacts repositories set-cleanup-policies "$AR_REPO" --location="$REGION" \
   --policy="$CLEANUP" --no-dry-run >/dev/null

cat <<EOF

Done. Set these as GitHub repository variables (not secrets; none is sensitive):

  gh variable set GCP_PROJECT_ID   --repo $GH_REPO --body "$PROJECT_ID"
  gh variable set GCP_REGION       --repo $GH_REPO --body "$REGION"
  gh variable set GCP_BUCKET       --repo $GH_REPO --body "$BUCKET"
  gh variable set GCP_WIF_PROVIDER --repo $GH_REPO --body "$PROVIDER_PATH"
  gh variable set GCP_DEPLOYER_SA  --repo $GH_REPO --body "$DEPLOYER"

Then run the workflow: Actions -> deploy -> Run workflow (or: gh workflow run deploy.yml).
EOF
