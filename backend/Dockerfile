FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System deps (kept minimal; classifier deps come in Phase 4)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first for layer caching
COPY pyproject.toml /app/
RUN pip install --upgrade pip && \
    pip install -e ".[dev]"

# Copy the rest of the app
COPY . /app

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
    CMD curl -fsS http://localhost:8000/healthz || exit 1

CMD ["flask", "--app", "app.wsgi", "run", "--host", "0.0.0.0", "--port", "8000"]
