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

FROM python:3.14.7-alpine3.24 AS worker-tools-builder

ENV PKG_CONFIG_PATH="/opt/ocr/lib/pkgconfig:/opt/poppler/lib/pkgconfig" \
    CPPFLAGS="-I/opt/ocr/include" \
    LDFLAGS="-L/opt/ocr/lib"

WORKDIR /src

RUN /sbin/apk add --no-cache \
        autoconf \
        automake \
        bash \
        boost-dev \
        build-base \
        cairo-dev \
        cmake \
        fontconfig-dev \
        giflib-dev \
        git \
        glib-dev \
        icu-dev \
        lcms2-dev \
        libjpeg-turbo-dev \
        libpng-dev \
        libtool \
        libwebp-dev \
        libxml2-dev \
        nss-dev \
        openjpeg-dev \
        pango-dev \
        samurai \
        zlib-dev

# libtiff 4.7.2: includes the upstream fixes for CVE-2023-52356 and CVE-2026-4775.
RUN python -c "import hashlib,urllib.request; u='https://download.osgeo.org/libtiff/tiff-4.7.2.tar.gz'; d=urllib.request.urlopen(u,timeout=120).read(); h=hashlib.sha512(d).hexdigest(); assert h=='bad66954a7e7e158c6dcbfc0e2d0032b8f3e2a354b6d0fdbb8038a7963e36c5b8a433dd4ee81c6c4dabfb50094152d440aa1f32b5299098c9ae29e55de2e41fc',h; open('/tmp/tiff.tar.gz','wb').write(d)" \
    && mkdir /src/tiff \
    && tar -xzf /tmp/tiff.tar.gz -C /src/tiff --strip-components=1 \
    && cmake -S /src/tiff -B /src/tiff/build -G Ninja \
        -DCMAKE_INSTALL_PREFIX=/opt/ocr \
        -DCMAKE_BUILD_TYPE=MinSizeRel \
        -DBUILD_SHARED_LIBS=ON \
    && cmake --build /src/tiff/build \
    && cmake --install /src/tiff/build \
    && rm -f /tmp/tiff.tar.gz

# Leptonica 1.87.0 built against the source-pinned libtiff above.
RUN python -c "import hashlib,urllib.request; u='https://github.com/DanBloomberg/leptonica/releases/download/1.87.0/leptonica-1.87.0.tar.gz'; d=urllib.request.urlopen(u,timeout=120).read(); h=hashlib.sha512(d).hexdigest(); assert h=='b689b1cfe4d5b884e7ede9d949149410117bbfbb85a1790c0516919f27e8746783c8a04cac9300c761d2736184fb4b2337ab6c3a2653fa9f69f82ba19b493a2d',h; open('/tmp/leptonica.tar.gz','wb').write(d)" \
    && mkdir /src/leptonica \
    && tar -xzf /tmp/leptonica.tar.gz -C /src/leptonica --strip-components=1 \
    && cd /src/leptonica \
    && autoreconf -fi \
    && ./configure --prefix=/opt/ocr --disable-static \
    && make -j2 \
    && make install \
    && rm -f /tmp/leptonica.tar.gz

# Tesseract pinned after all published CVE-2026-88047..88054 fix commits.
RUN git init /src/tesseract \
    && cd /src/tesseract \
    && git remote add origin https://github.com/tesseract-ocr/tesseract.git \
    && git fetch --depth 1 origin 8ae68101439b3f7df123499a784e8896c805179d \
    && git checkout --detach FETCH_HEAD \
    && test "$(git rev-parse HEAD)" = "8ae68101439b3f7df123499a784e8896c805179d" \
    && ./autogen.sh \
    && ./configure --prefix=/opt/ocr --disable-static \
    && make -j2 \
    && make install

# Poppler utilities are built from the Alpine-verified upstream tarball against /opt/ocr.
RUN python -c "import hashlib,urllib.request; u='https://poppler.freedesktop.org/poppler-25.12.0.tar.xz'; d=urllib.request.urlopen(u,timeout=120).read(); h=hashlib.sha512(d).hexdigest(); assert h=='4f68713d7efa5003a60773749d3bcff4041b165dfb65104a56cec576559c15164fc4a021244cc91f4ed76aab709757637396d7c5b6fbcf3eed23e3469072e4f3',h; open('/tmp/poppler.tar.xz','wb').write(d)" \
    && mkdir /src/poppler \
    && tar -xJf /tmp/poppler.tar.xz -C /src/poppler --strip-components=1 \
    && cmake -S /src/poppler -B /src/poppler/build -G Ninja \
        -DCMAKE_INSTALL_PREFIX=/opt/poppler \
        -DCMAKE_PREFIX_PATH=/opt/ocr \
        -DCMAKE_BUILD_TYPE=RelWithDebInfo \
        -DENABLE_GPGME=OFF \
        -DENABLE_LIBCURL=OFF \
        -DENABLE_QT5=OFF \
        -DENABLE_QT6=OFF \
        -DENABLE_UNSTABLE_API_ABI_HEADERS=OFF \
        -DBUILD_CPP_TESTS=OFF \
        -DBUILD_GTK_TESTS=OFF \
        -DBUILD_MANUAL_TESTS=OFF \
        -DBUILD_QT5_TESTS=OFF \
        -DBUILD_QT6_TESTS=OFF \
    && cmake --build /src/poppler/build -j2 \
    && cmake --install /src/poppler/build \
    && rm -f /tmp/poppler.tar.xz

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
    PATH="/opt/venv/bin:/opt/ocr/bin:/opt/poppler/bin:/usr/local/bin:/usr/bin:/bin" \
    LD_LIBRARY_PATH="/opt/ocr/lib:/opt/poppler/lib" \
    TESSDATA_PREFIX="/usr/share/tessdata"

WORKDIR /app

RUN /sbin/apk add --no-cache \
        --repository=https://dl-cdn.alpinelinux.org/alpine/v3.19/main \
        'zlib=1.3.1-r0' \
    && /sbin/apk add --no-cache \
        cairo \
        ca-certificates \
        fontconfig \
        giflib \
        glib \
        icu-libs \
        lcms2 \
        libgcc \
        libgomp \
        libjpeg-turbo \
        libpng \
        libstdc++ \
        libwebp \
        libwebpmux \
        libxml2 \
        nss \
        openjpeg \
        pango \
    && /sbin/apk info -v zlib \
    && python -c "import hashlib,pathlib,urllib.request; files=[('eng.traineddata',23466654,'f4744c201359d02ced6914c77f0de68ee9bbdd74'),('fas.traineddata',561272,'a0b9843164d928caad5afb0bd6973c964ba5b0b9')]; base='https://raw.githubusercontent.com/tesseract-ocr/tessdata/ced78752cc61322fb554c280d13360b35b8684e4/'; out=pathlib.Path('/usr/share/tessdata'); out.mkdir(parents=True,exist_ok=True); [(lambda name,size,want: (lambda data: ((_ for _ in ()).throw(AssertionError(len(data))) if len(data)!=size else None, (_ for _ in ()).throw(AssertionError('git sha mismatch')) if hashlib.sha1(b'blob '+str(len(data)).encode()+b'\\0'+data).hexdigest()!=want else None, print(name+'.sha256='+hashlib.sha256(data).hexdigest()), (out/name).write_bytes(data)))(urllib.request.urlopen(base+name,timeout=120).read()))(name,size,want) for name,size,want in files]" \
    && rm -rf /usr/local/lib/python3.14/site-packages/pip* /usr/local/bin/pip*

COPY --from=worker-tools-builder /opt/ocr /opt/ocr
COPY --from=worker-tools-builder /opt/poppler /opt/poppler
COPY --from=python-builder /opt/venv /opt/venv

RUN python --version \
    && tesseract --version | head -n 2 \
    && pdftotext -v 2>&1 | head -n 1 \
    && pdftoppm -v 2>&1 | head -n 1 \
    && ldd /opt/ocr/bin/tesseract \
    && ldd /opt/poppler/bin/pdftotext \
    && ldd /opt/poppler/bin/pdftoppm \
    && ! /sbin/apk info -e tiff \
    && ! /sbin/apk info -e leptonica \
    && ! /sbin/apk info -e tesseract-ocr \
    && ! /sbin/apk info -e poppler \
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
