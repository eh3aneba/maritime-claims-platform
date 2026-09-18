FROM cgr.dev/chainguard/wolfi-base:latest AS python-builder

WORKDIR /app

RUN apk add --no-cache \
        build-base \
        libuuid \
        py3.13-pip \
        python-3.13 \
        zlib \
    && python3.13 --version \
    && pip3.13 --version

COPY requirements.lock .
RUN pip3.13 install --no-cache-dir --require-hashes --prefix=/install -r requirements.lock

FROM cgr.dev/chainguard/wolfi-base:latest AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/usr/local/bin:/usr/bin:/bin"

WORKDIR /app

RUN apk add --no-cache \
        libuuid \
        python-3.13 \
        zlib \
    && python3.13 -c "import _uuid, uuid, zlib; value = uuid.uuid4(); assert value.version == 4; print(value, zlib.ZLIB_VERSION)"

COPY --from=python-builder /install/ /usr/local/
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

CMD ["python3.13", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
