FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/cache/huggingface \
    TRANSFORMERS_CACHE=/cache/huggingface \
    XDG_CACHE_HOME=/cache

WORKDIR /app

# System deps. `libpq-dev` for psycopg, `curl` for healthcheck, `git` so HF
# can pull repos when needed.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        git \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first for layer caching. We add the PyTorch CPU wheel
# index so torch installs as +cpu (a few hundred MB instead of multi-GB CUDA).
COPY pyproject.toml /app/
RUN pip install --upgrade pip && \
    pip install --extra-index-url https://download.pytorch.org/whl/cpu \
        -e ".[dev]"

# spaCy English model — required by Presidio for NER (PERSON/LOCATION/NRP).
# Bakes into the image so workers don't have to download at runtime.
RUN python -m spacy download en_core_web_lg

# Cache directory for HuggingFace model downloads; mounted as a Docker volume
# in compose so model pulls persist across container restarts.
RUN mkdir -p /cache/huggingface

# Copy the rest of the app
COPY . /app

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
    CMD curl -fsS http://localhost:8000/healthz || exit 1

CMD ["flask", "--app", "app.wsgi", "run", "--host", "0.0.0.0", "--port", "8000"]
