FROM alpine:3.24.2@sha256:5b02b42e375f7426f8d65c3af331ca05d9878f9989230354504e0b9dfd431f60 AS python-builder

WORKDIR /app

RUN apk add --no-cache \
        build-base \
        libffi-dev \
        libuuid \
        openssl-dev \
        py3-pip \
        python3 \
        python3-dev \
        zlib-dev \
    && python3 --version \
    && python3 -m pip --version

COPY requirements.lock .
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/python -m pip install --no-cache-dir --require-hashes -r requirements.lock \
    && /opt/venv/bin/python -m pip check \
    && /opt/venv/bin/python -c "import alembic, fastapi, sqlalchemy; print('venv-ready')"

FROM alpine:3.24.2@sha256:5b02b42e375f7426f8d65c3af331ca05d9878f9989230354504e0b9dfd431f60 AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:/usr/bin:/bin"

WORKDIR /app

RUN apk add --no-cache \
        libuuid \
        python3 \
        zlib \
    && python3 -c "import _uuid, uuid, zlib; value = uuid.uuid4(); assert value.version == 4; print(value, zlib.ZLIB_VERSION)"

COPY --from=python-builder /opt/venv /opt/venv
COPY pyproject.toml alembic.ini ./
COPY alembic ./alembic
COPY app ./app

EXPOSE 8000

FROM alpine:3.24.2@sha256:5b02b42e375f7426f8d65c3af331ca05d9878f9989230354504e0b9dfd431f60 AS worker

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:/usr/bin:/bin" \
    TESSDATA_PREFIX="/usr/share/tessdata"

WORKDIR /app

RUN apk add --no-cache \
        libuuid \
        poppler-utils \
        python3 \
        tesseract-ocr \
        tesseract-ocr-data-fas \
        zlib \
    && python3 --version \
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

CMD ["python3", "-m", "app.workers.document_worker"]

FROM base AS api

CMD ["python3", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
