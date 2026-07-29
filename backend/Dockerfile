# ClinicQ backend — one process: webhook + panel API + queue engine + scheduler.
FROM python:3.11-slim

# UTC container clock; the scheduler uses explicit IST trigger objects.
ENV TZ=UTC \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# curl is used by the compose healthcheck.
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# pyproject drives the install (setuptools finds app*). Copy both, then install.
COPY pyproject.toml ./
COPY app ./app
RUN pip install --upgrade pip && pip install .

EXPOSE 8000

# SINGLE WORKER — the in-process APScheduler must not be duplicated.
# (See DEPLOY.md §scheduler single-instance.) Do not add --workers >1 here.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
