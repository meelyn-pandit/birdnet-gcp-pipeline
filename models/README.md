# models/

Trained classifiers (`*.joblib`), not committed. Each file is a dict with
the fitted model plus what is needed to use and audit it: species,
threshold, embedding model, the recordings it was trained on, and its
held-out test estimate (with a pointer to the report in `reports/`).

```python
from birdnet_pipeline.classifier import load_bundle
b = load_bundle("models/field_sparrow_perch.joblib")
print({k: v for k, v in b.items() if k != "model"})
```

Create or refresh one with `bgp-evaluate --species "..." --save models/<name>.joblib`.
