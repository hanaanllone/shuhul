# The Shuhul API and worker. One image, two commands:
#   API     gunicorn (the default)
#   worker  python -m backend.worker
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/shuhul

# The raster and vector wheels carry their own GDAL, which needs libexpat.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libexpat1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY backend backend
COPY articles articles
COPY districts-geojson districts-geojson

# Data is mounted, never baked in. Outputs get a folder the app user owns.
RUN useradd --create-home shuhul \
    && mkdir -p /data/processed /data/outputs \
    && chown -R shuhul:shuhul /data
USER shuhul

ENV SHUHUL_ENV=production \
    SHUHUL_PROCESSED_ROOT=/data/processed \
    SHUHUL_OUTPUT_ROOT=/data/outputs

EXPOSE 8000

# One process with threads: the tables are created once at start, and the
# sign-in rate limit is kept in memory.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "8", "--timeout", "180", "--access-logfile", "-", "backend.app:app"]
