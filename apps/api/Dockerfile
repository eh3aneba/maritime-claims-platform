FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Probe a supported Debian-slim base while preserving Python 3.13.
# Install the current signed distro packages for UUID and zlib; the mandatory
# image vulnerability scan remains authoritative and fail-closed.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libuuid1 zlib1g \
    && rm -rf /var/lib/apt/lists/* \
    && python -c "import _uuid, uuid; value = uuid.uuid4(); assert value.version == 4; print(value)"

COPY requirements.lock .
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

COPY pyproject.toml alembic.ini ./
COPY alembic ./alembic
COPY app ./app

EXPOSE 8000

FROM python:3.13-slim AS worker

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        poppler-utils \
        tesseract-ocr \
        tesseract-ocr-eng \
        tesseract-ocr-fas \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.lock .
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

COPY pyproject.toml alembic.ini ./
COPY alembic ./alembic
COPY app ./app

CMD ["python", "-m", "app.workers.document_worker"]

FROM base AS api

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
