FROM python:3.14.7-alpine3.24 AS python-builder

WORKDIR /app

RUN apk add --no-cache \
        build-base \
        libffi-dev \
        libuuid \
        openssl-dev \
        zlib-dev \
    && python --version \
    && python -m pip --version

COPY requirements.lock .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/python -m pip install --no-cache-dir --require-hashes -r requirements.lock \
    && /opt/venv/bin/python -m pip check \
    && /opt/venv/bin/python -c "import alembic, fastapi, sqlalchemy; print('venv-ready')"

FROM python:3.14.7-alpine3.24 AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:/usr/local/bin:/usr/bin:/bin"

WORKDIR /app

RUN apk add --no-cache libuuid zlib \
    && python -c "import _uuid, uuid, zlib; value = uuid.uuid4(); assert value.version == 4; print(value, zlib.ZLIB_VERSION)" \
    && rm -rf /usr/local/lib/python3.14/site-packages/pip* /usr/local/bin/pip*

COPY --from=python-builder /opt/venv /opt/venv
COPY pyproject.toml alembic.ini ./
COPY alembic ./alembic
COPY app ./app

EXPOSE 8000

FROM python:3.14.7-alpine3.24 AS worker

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:/usr/local/bin:/usr/bin:/bin" \
    TESSDATA_PREFIX="/usr/share/tessdata"

WORKDIR /app

RUN apk add --no-cache \
        libuuid \
        poppler-utils \
        tesseract-ocr \
        tesseract-ocr-data-eng \
        tesseract-ocr-data-fas \
        zlib \
    && python --version \
    && pdftotext -v 2>&1 | head -n 1 \
    && pdftoppm -v 2>&1 | head -n 1 \
    && tesseract --version | head -n 1 \
    && test -f /usr/share/tessdata/eng.traineddata \
    && test -f /usr/share/tessdata/fas.traineddata \
    && tesseract --list-langs | tee /tmp/tesseract-langs.txt \
    && grep -Fx eng /tmp/tesseract-langs.txt \
    && grep -Fx fas /tmp/tesseract-langs.txt \
    && rm -f /tmp/tesseract-langs.txt \
    && rm -rf /usr/local/lib/python3.14/site-packages/pip* /usr/local/bin/pip*

COPY --from=python-builder /opt/venv /opt/venv
COPY pyproject.toml alembic.ini ./
COPY alembic ./alembic
COPY app ./app

CMD ["python", "-m", "app.workers.document_worker"]

FROM base AS api

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
