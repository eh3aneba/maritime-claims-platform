FROM python:3.13-alpine AS libuuid-builder

ARG UTIL_LINUX_VERSION=2.42.3
ARG UTIL_LINUX_SHA256=66ac7c0e725278eb2b039e3104f2c91119341d941b41bac7a285c695f940bd57

RUN apk add --no-cache build-base linux-headers \
    && wget -q -O /tmp/util-linux.tar.xz \
        "https://www.kernel.org/pub/linux/utils/util-linux/v2.42/util-linux-${UTIL_LINUX_VERSION}.tar.xz" \
    && echo "${UTIL_LINUX_SHA256}  /tmp/util-linux.tar.xz" | sha256sum -c - \
    && tar -xJf /tmp/util-linux.tar.xz -C /tmp \
    && cd "/tmp/util-linux-${UTIL_LINUX_VERSION}" \
    && ./configure \
        --prefix=/usr \
        --libdir=/usr/lib \
        --disable-all-programs \
        --enable-libuuid \
        --without-python \
        --disable-pylibmount \
        --without-readline \
        --without-audit \
        --without-libmagic \
    && make -j"$(getconf _NPROCESSORS_ONLN)" \
    && make DESTDIR=/pkg install \
    && rm -rf \
        /pkg/usr/bin \
        /pkg/usr/sbin \
        /pkg/usr/include \
        /pkg/usr/lib/pkgconfig \
        /pkg/usr/share \
    && ARCH="$(apk --print-arch)" \
    && apk mkpkg \
        --files /pkg \
        --info name:libuuid \
        --info version:${UTIL_LINUX_VERSION}-r0 \
        --info arch:${ARCH} \
        --info description:"DCE compatible Universally Unique Identifier library" \
        --info license:BSD-3-Clause \
        --info origin:util-linux \
        --info url:https://www.kernel.org/pub/linux/utils/util-linux/ \
        --info depends:musl \
        --info provides:so:libuuid.so.1=1 \
        --output "/tmp/libuuid-${UTIL_LINUX_VERSION}-r0.apk"

FROM python:3.13-alpine AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY --from=libuuid-builder /tmp/libuuid-2.42.3-r0.apk /tmp/libuuid-2.42.3-r0.apk
RUN apk add --no-cache --allow-untrusted --upgrade /tmp/libuuid-2.42.3-r0.apk \
    && apk info -v libuuid | grep -Fx 'libuuid-2.42.3-r0' \
    && python -c "import _uuid, uuid; value = uuid.uuid4(); assert value.version == 4; print(value)" \
    && rm -f /tmp/libuuid-2.42.3-r0.apk

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
