# Budget kill switch

Hard $10/month spending cap for the `birdnet-pipeline` project.

A Cloud Billing budget ($10/month, scoped to this project) publishes spend
updates to the Pub/Sub topic `budget-alerts`. The Cloud Function
`budget-killswitch` (us-central1) reads each update and, once
`costAmount >= budgetAmount`, **removes the billing account from the project**.
Paid services then stop.

## Caveats

- **Not instant.** Billing data reaches budgets with a lag of up to about a
  day, so actual spend can go somewhat past $10 before shutoff.
- **Destructive if left off.** With billing removed, resources stop serving,
  and Cloud Storage objects and other data can be deleted if billing stays
  off. Re-link billing promptly if you want to keep the data.
- **Re-enabling:** Console > Billing > Account management > link
  `birdnet-pipeline` to your billing account, or:
  `gcloud billing projects link birdnet-pipeline --billing-account=BILLING_ACCOUNT_ID`

## Resources

| Resource | Name |
|---|---|
| Budget | `birdnet-pipeline $10 hard cap` on billing account BILLING_ACCOUNT_ID; thresholds 50/90/100% |
| Topic | `projects/birdnet-pipeline/topics/budget-alerts` |
| Function | `budget-killswitch`, gen2, python312, us-central1 |
| Service account | `budget-killswitch@birdnet-pipeline.iam.gserviceaccount.com` with `roles/billing.projectManager` on the project and `roles/run.invoker` on the function |

## Redeploy

```bash
gcloud functions deploy budget-killswitch --gen2 --project=birdnet-pipeline \
  --region=us-central1 --runtime=python312 --source=infra/budget_killswitch \
  --entry-point=stop_billing --trigger-topic=budget-alerts \
  --service-account=budget-killswitch@birdnet-pipeline.iam.gserviceaccount.com \
  --set-env-vars=TARGET_PROJECT_ID=birdnet-pipeline --max-instances=1 --memory=256Mi

# Required, or every trigger delivery fails with 403:
gcloud run services add-iam-policy-binding budget-killswitch --region=us-central1 \
  --member=serviceAccount:budget-killswitch@birdnet-pipeline.iam.gserviceaccount.com \
  --role=roles/run.invoker --project=birdnet-pipeline
```

## Safe test (under budget, no shutoff)

```bash
gcloud pubsub topics publish budget-alerts --project=birdnet-pipeline \
  --message='{"costAmount": 3.0, "budgetAmount": 10.0, "currencyCode": "USD"}'
```

Logs should show `Under budget; no action.`
