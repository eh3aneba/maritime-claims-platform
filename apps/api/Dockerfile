FROM cgr.dev/chainguard/wolfi-base@sha256:1d95114038f76513a9ace6fca107d5582b08c65981f81f61cb56bf7fd2ef216d AS python-builder

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
RUN python3.13 -m venv /opt/venv \
    && /opt/venv/bin/python -m pip install --no-cache-dir --require-hashes -r requirements.lock \
    && /opt/venv/bin/python -c "import alembic, fastapi, sqlalchemy; print('venv-ready')"

FROM cgr.dev/chainguard/wolfi-base@sha256:1d95114038f76513a9ace6fca107d5582b08c65981f81f61cb56bf7fd2ef216d AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:/usr/bin:/bin"

WORKDIR /app

RUN apk add --no-cache \
        libuuid \
        python-3.13 \
        zlib \
    && python3.13 -c "import _uuid, uuid, zlib; value = uuid.uuid4(); assert value.version == 4; print(value, zlib.ZLIB_VERSION)"

COPY --from=python-builder /opt/venv /opt/venv
COPY pyproject.toml alembic.ini ./
COPY alembic ./alembic
COPY app ./app

EXPOSE 8000

FROM cgr.dev/chainguard/wolfi-base@sha256:1d95114038f76513a9ace6fca107d5582b08c65981f81f61cb56bf7fd2ef216d AS worker

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:/usr/bin:/bin" \
    TESSDATA_PREFIX="/usr/share/tessdata"

WORKDIR /app

RUN apk add --no-cache \
        libuuid \
        poppler-utils \
        python-3.13 \
        tessdata \
        tesseract \
        zlib \
    && python3.13 --version \
    && pdftotext -v 2>&1 | head -n 1 \
    && pdftoppm -v 2>&1 | head -n 1 \
    && tesseract --version | head -n 1 \
    && test -f /usr/share/tessdata/eng.traineddata \
    && test -f /usr/share/tessdata/fas.traineddata \
    && tesseract --list-langs | tee /tmp/tesseract-langs.txt \
    && grep -Fx eng /tmp/tesseract-langs.txt \
    && grep -Fx fas /tmp/tesseract-langs.txt \
    && rm -f /tmp/tesseract-langs.txt

COPY --from=python-builder /opt/venv /opt/venv
COPY pyproject.toml alembic.ini ./
COPY alembic ./alembic
COPY app ./app

CMD ["python", "-m", "app.workers.document_worker"]

FROM base AS api

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
