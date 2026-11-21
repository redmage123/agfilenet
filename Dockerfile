# syntax=docker/dockerfile:1

# --- React front end ---------------------------------------------------------
FROM node:20-slim AS frontend
WORKDIR /build
COPY src/frontend/package.json src/frontend/package-lock.json ./
RUN npm ci
COPY src/frontend/ ./
RUN npm run build

# --- application -------------------------------------------------------------
FROM python:3.12-slim
# libGL/glib are needed by OpenCV, which the OCR engine uses
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src/backend \
    FASTEMBED_CACHE_PATH=/opt/models \
    MALLOC_ARENA_MAX=2 \
    AGFILENET_DATA=/data \
    AGFILENET_VAR=/var/lib/agfilenet

WORKDIR /app
COPY src/backend/requirements.txt src/backend/requirements.txt
# the extra index has prebuilt CPU wheels of llama-cpp-python, so no compiler is needed
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir --only-binary=llama-cpp-python \
        --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu \
        -r src/backend/requirements.txt

# Fetch the models while building, so the running container never needs the
# network: documents are read, OCR'd, embedded and answered about inside it.
# Only the two files that say which models are copied first, so that a change
# to the code does not download them again. WITH_LLM=0 leaves out the language
# model (about 1 GB); "Ask" and "deeper search" are then switched off.
ARG WITH_LLM=1
COPY src/backend/agfilenet/__init__.py src/backend/agfilenet/config.py src/backend/agfilenet/models.py \
     src/backend/agfilenet/
RUN python -c "from agfilenet import models; models.fetch_all(llm='${WITH_LLM}' == '1')" \
    && chmod -R a+rX /opt/models
ENV HF_HUB_OFFLINE=1

COPY src/backend/agfilenet src/backend/agfilenet
COPY --from=frontend /build/dist src/frontend/dist

# Runs as an unprivileged user; compose overrides this with your own uid so the
# database files in ./var stay yours.
# The code must be readable whatever the permissions of the build context were.
RUN chmod -R a+rX /app/src \
    && mkdir -p /data /var/lib/agfilenet && chown 1000:1000 /var/lib/agfilenet
USER 1000:1000
VOLUME ["/data", "/var/lib/agfilenet"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/status', timeout=4)"

ENTRYPOINT ["python", "-m", "agfilenet"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
