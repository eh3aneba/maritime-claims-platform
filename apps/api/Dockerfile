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

FROM python:3.14.7-alpine3.24 AS tesseract-builder

RUN /sbin/apk add --no-cache \
        autoconf \
        automake \
        build-base \
        cairo-dev \
        git \
        icu-dev \
        leptonica-dev \
        libtool \
        pango-dev

RUN git init /src/tesseract \
    && cd /src/tesseract \
    && git remote add origin https://github.com/tesseract-ocr/tesseract.git \
    && git fetch --depth 1 origin 8ae68101439b3f7df123499a784e8896c805179d \
    && git checkout --detach FETCH_HEAD \
    && test "$(git rev-parse HEAD)" = "8ae68101439b3f7df123499a784e8896c805179d" \
    && printf '5.5.4\n' > VERSION \
    && ./autogen.sh \
    && ./configure --prefix=/opt/tesseract --disable-static \
    && make -j2 \
    && make install \
    && /opt/tesseract/bin/tesseract --version

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

FROM python:3.14.7-alpine3.24 AS worker

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:/opt/tesseract/bin:/usr/local/bin:/usr/bin:/bin" \
    LD_LIBRARY_PATH="/opt/tesseract/lib" \
    TESSDATA_PREFIX="/usr/share/tessdata"

WORKDIR /app

RUN /sbin/apk add --no-cache \
        --repository=https://dl-cdn.alpinelinux.org/alpine/v3.19/main \
        'zlib=1.3.1-r0' \
    && /sbin/apk add --no-cache \
        --repository=https://dl-cdn.alpinelinux.org/alpine/edge/main \
        'tiff=4.7.2-r0' \
    && /sbin/apk add --no-cache \
        ca-certificates \
        cairo \
        icu-libs \
        leptonica \
        libgomp \
        libstdc++ \
        pango \
        poppler-utils \
    && /sbin/apk info -v zlib tiff \
    && python -c "import hashlib,pathlib,urllib.request; files=[('eng.traineddata',23466654,'f4744c201359d02ced6914c77f0de68ee9bbdd74'),('fas.traineddata',561272,'a0b9843164d928caad5afb0bd6973c964ba5b0b9')]; base='https://raw.githubusercontent.com/tesseract-ocr/tessdata/ced78752cc61322fb554c280d13360b35b8684e4/'; out=pathlib.Path('/usr/share/tessdata'); out.mkdir(parents=True,exist_ok=True); [(lambda name,size,want: (lambda data: ( (_ for _ in ()).throw(AssertionError(len(data))) if len(data)!=size else None, (_ for _ in ()).throw(AssertionError('git sha mismatch')) if hashlib.sha1(b'blob '+str(len(data)).encode()+b'\\0'+data).hexdigest()!=want else None, print(name+'.sha256='+hashlib.sha256(data).hexdigest()), (out/name).write_bytes(data)))(urllib.request.urlopen(base+name,timeout=60).read()))(name,size,want) for name,size,want in files]" \
    && rm -rf /usr/local/lib/python3.14/site-packages/pip* /usr/local/bin/pip*

COPY --from=tesseract-builder /opt/tesseract /opt/tesseract
COPY --from=python-builder /opt/venv /opt/venv

RUN python --version \
    && pdftotext -v 2>&1 | head -n 1 \
    && pdftoppm -v 2>&1 | head -n 1 \
    && tesseract --version | head -n 1 \
    && ldd /opt/tesseract/bin/tesseract \
    && test -f /usr/share/tessdata/eng.traineddata \
    && test -f /usr/share/tessdata/fas.traineddata \
    && tesseract --list-langs | tee /tmp/tesseract-langs.txt \
    && grep -Fx eng /tmp/tesseract-langs.txt \
    && grep -Fx fas /tmp/tesseract-langs.txt \
    && rm -f /tmp/tesseract-langs.txt

COPY pyproject.toml alembic.ini ./
COPY alembic ./alembic
COPY app ./app

CMD ["python", "-m", "app.workers.document_worker"]

FROM base AS api

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
