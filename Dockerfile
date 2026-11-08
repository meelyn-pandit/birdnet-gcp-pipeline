# Detection image: BirdNET + Perch v2 + birdnet_pipeline, CPU only.
# Both models are downloaded at build time so tasks start without network fetches.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    KAGGLEHUB_CACHE=/opt/models/kagglehub \
    TF_CPP_MIN_LOG_LEVEL=2

RUN apt-get update \
 && apt-get install -y --no-install-recommends libsndfile1 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Exact, tested dependency versions first (cached layer), then the package.
COPY requirements.lock .
RUN pip install -r requirements.lock

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-deps .

COPY configs/region.toml configs/species.toml ./configs/

# Bake in the BirdNET checkpoints and the Perch v2 model (~650 MB together).
RUN python -c "from birdnet_analyzer.utils import ensure_model_exists; ensure_model_exists()" \
 && python -c "from birdnet_pipeline.detectors.perch import load_model; load_model()"

ENV BGP_ROOT=/app
ENTRYPOINT ["bgp-detect", "--config", "/app/configs/region.toml"]
