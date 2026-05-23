# Multi-stage build:
#   1. ``builder`` installs Poetry-managed deps into a virtualenv
#   2. ``runtime`` copies the virtualenv + source into a slim image
# Web, beat, and worker_* containers all use the same image — they differ
# only in their startup command (see docker-compose.yml).

FROM python:3.12-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VERSION=1.8.3 \
    POETRY_HOME=/opt/poetry \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=true

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
      curl \
      libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN curl -sSL https://install.python-poetry.org | python3 -
ENV PATH="${POETRY_HOME}/bin:${PATH}"

WORKDIR /app
COPY pyproject.toml poetry.lock ./
RUN poetry install --no-root --without dev

FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}" \
    DJANGO_SETTINGS_MODULE=interactome.settings.production

RUN apt-get update && apt-get install -y --no-install-recommends \
      libpq5 \
      curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 1000 app \
    && useradd --system --uid 1000 --gid app --no-create-home app

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --chown=app:app . .

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -f http://localhost:8000/health/ || exit 1

CMD ["gunicorn", "interactome.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "4", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
