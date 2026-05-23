# IVD Regulatory Network Atlas

Autonomous PubMed → SBML-qual pipeline for intervertebral disc regulatory
networks. Built as a Django application hosted alongside the SIMBIOsys
Ollama gateway.

## Documentation

- [Full design specification](docs/superpowers/specs/2026-05-19-disc-interactome-app-design.md)
- [Phase 0 implementation plan (this is what's been built)](docs/superpowers/plans/2026-05-19-phase-0-foundation.md)

## Prerequisites

- Python 3.12
- Poetry 1.8+
- Docker Engine 24+ and Docker Compose v2
- 32 GB RAM, 200 GB disk available
- Access to the SIMBIOsys cluster Ollama gateway and Authelia SSO

## Local development

```bash
git clone git@github.com:SpineView1/IVD-Regulatory-Network-Atlas.git
cd IVD-Regulatory-Network-Atlas
cp .env.example .env
# Edit .env and fill in real values for DJANGO_SECRET_KEY, POSTGRES_PASSWORD, etc.
poetry install
poetry run python manage.py migrate
poetry run python manage.py runserver
```

Open `http://localhost:8000/health/`. You should see:

```json
{ "user": "fchemorion", "database": "ok" }
```

(`user` is `fchemorion` because the dev settings set
`AUTHELIA_DEV_FAKE_USER`. In production this is `None` and the
middleware reads the `Remote-User` header from Authelia.)

## Running the full stack locally (docker-compose)

```bash
docker-compose up -d
docker-compose ps         # check all 8 services are healthy
docker-compose logs -f web
```

Then `curl https://localhost/health/` (you'll need a TLS cert override for
the self-signed dev cert, or hit `http://localhost:8000/health/`
directly bypassing Caddy).

## Running tests

```bash
poetry run pytest
```

Lint and type checks:

```bash
poetry run ruff check .
poetry run ruff format --check .
poetry run mypy apps interactome
```

## Project layout

See [the design spec](docs/superpowers/specs/2026-05-19-disc-interactome-app-design.md#2-django-apps-and-module-boundaries)
for the full architecture. Phase 0 contains only the `core` app; subsequent
phases add `networks`, `corpus`, `papers`, `extract`, `graph`, `sbml`,
`verify`, `schedule`, and `dashboard`.

## Deployment

The cluster host runs the same `docker-compose.yml`. See
[Section 9 of the spec](docs/superpowers/specs/2026-05-19-disc-interactome-app-design.md#9-deployment-and-operations)
for IT prerequisites (DNS, Authelia AD group) and the deploy procedure.

## License

UPF / SIMBIOsys research code. Contact Francis Chemorion before
redistributing.
