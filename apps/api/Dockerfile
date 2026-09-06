FROM python:3.13-alpine AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Use Alpine's signed security-updated util-linux/libuuid package rather than maintaining
# a private repack of upstream source. CVE-2026-78408 is fixed in Alpine libuuid 2.42.3-r1.
# The minimum-version constraint keeps the build fail-closed if an older repository snapshot
# is ever selected while allowing later signed security revisions to supersede r1.
RUN apk add --no-cache --upgrade 'libuuid>=2.42.3-r1' \
    && apk info --installed 'libuuid>=2.42.3-r1' >/dev/null \
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
