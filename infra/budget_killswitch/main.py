"""Budget kill switch: unlink billing from the project when spend >= budget.

Triggered by Cloud Billing budget notifications on Pub/Sub. When the
reported cost reaches the budget amount, it removes the billing account
from the project, which stops all paid services.

WARNING: with billing removed, paid resources stop working, and some
(e.g. Cloud Storage data) can be deleted if billing is not re-enabled.
Re-link billing in the Console (Billing > Account management) to restore.
"""
import base64
import json
import os

import functions_framework
from googleapiclient import discovery

PROJECT_ID = os.environ["TARGET_PROJECT_ID"]
PROJECT_NAME = f"projects/{PROJECT_ID}"


@functions_framework.cloud_event
def stop_billing(cloud_event):
    data = json.loads(base64.b64decode(cloud_event.data["message"]["data"]).decode())
    cost, budget = data.get("costAmount", 0), data.get("budgetAmount", 0)
    print(f"Budget notification: cost={cost} budget={budget} {data.get('currencyCode')}")

    if budget <= 0 or cost < budget:
        print("Under budget; no action.")
        return

    billing = discovery.build("cloudbilling", "v1", cache_discovery=False)
    projects = billing.projects()
    info = projects.getBillingInfo(name=PROJECT_NAME).execute()
    if not info.get("billingEnabled"):
        print("Billing already disabled.")
        return

    projects.updateBillingInfo(name=PROJECT_NAME, body={"billingAccountName": ""}).execute()
    print(f"Billing DISABLED for {PROJECT_ID}: cost {cost} >= budget {budget}")
