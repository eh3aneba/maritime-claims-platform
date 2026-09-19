FROM python:3.14.7-alpine3.24 AS python-builder

WORKDIR /app

RUN /sbin/apk add --no-cache \
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

FROM python:3.14.7-slim-trixie AS worker-python-builder

WORKDIR /app

COPY requirements.lock .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/python -m pip install --no-cache-dir --require-hashes -r requirements.lock \
    && /opt/venv/bin/python -m pip check \
    && /opt/venv/bin/python -c "import alembic, fastapi, sqlalchemy; print('worker-venv-ready')"

FROM python:3.14.7-alpine3.24 AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:/usr/local/bin:/usr/bin:/bin"

WORKDIR /app

RUN /sbin/apk add --no-cache \
        --repository=https://dl-cdn.alpinelinux.org/alpine/v3.19/main \
        'zlib=1.3.1-r0' \
    && /sbin/apk add --no-cache libuuid \
    && /sbin/apk info -v zlib \
    && python -c "import _uuid, uuid, zlib; value = uuid.uuid4(); assert value.version == 4; print(value, zlib.ZLIB_VERSION)" \
    && rm -rf /usr/local/lib/python3.14/site-packages/pip* /usr/local/bin/pip*

COPY --from=python-builder /opt/venv /opt/venv
COPY pyproject.toml alembic.ini ./
COPY alembic ./alembic
COPY app ./app

EXPOSE 8000

FROM python:3.14.7-slim-trixie AS worker

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:/usr/local/bin:/usr/bin:/bin" \
    TESSDATA_PREFIX="/usr/share/tesseract-ocr/5/tessdata"

WORKDIR /app

RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends \
        libuuid1 \
        poppler-utils \
        tesseract-ocr \
        tesseract-ocr-eng \
        tesseract-ocr-fas \
        zlib1g \
    && rm -rf /var/lib/apt/lists/* /usr/local/lib/python3.14/site-packages/pip* /usr/local/bin/pip* \
    && python --version \
    && pdftotext -v 2>&1 | head -n 1 \
    && pdftoppm -v 2>&1 | head -n 1 \
    && tesseract --version | head -n 1 \
    && test -f /usr/share/tesseract-ocr/5/tessdata/eng.traineddata \
    && test -f /usr/share/tesseract-ocr/5/tessdata/fas.traineddata \
    && tesseract --list-langs | tee /tmp/tesseract-langs.txt \
    && grep -Fx eng /tmp/tesseract-langs.txt \
    && grep -Fx fas /tmp/tesseract-langs.txt \
    && rm -f /tmp/tesseract-langs.txt

COPY --from=worker-python-builder /opt/venv /opt/venv
COPY pyproject.toml alembic.ini ./
COPY alembic ./alembic
COPY app ./app

CMD ["python", "-m", "app.workers.document_worker"]

FROM base AS api

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
