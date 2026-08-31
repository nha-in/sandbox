export COMPOSE_FILE := "docker-compose.local.yml"

## Just does not yet manage signals for subprocesses reliably, which can lead to unexpected behavior.
## Exercise caution before expanding its usage in production environments.
## For more information, see https://github.com/casey/just/issues/2473 .


# Default command to list all available commands.
default:
    @just --list

# bootstrap: Everything from a fresh clone to a running, seeded portal.
bootstrap:
    @test -f .envs/.local/.django   || cp .envs/.local/.django.example   .envs/.local/.django
    @test -f .envs/.local/.postgres || cp .envs/.local/.postgres.example .envs/.local/.postgres
    @echo "Building images..."
    @docker compose build
    @echo "Starting containers..."
    @docker compose up -d --remove-orphans
    @echo "Applying migrations..."
    @docker compose run --rm django python manage.py migrate
    @echo "Seeding demo data..."
    @docker compose run --rm django python manage.py seed_sandbox_demo
    @just urls

# urls: Where everything is listening.
urls:
    @echo ""
    @echo "  portal    http://localhost:8000"
    @echo "  mailpit   http://localhost:8025"
    @echo "  flower    http://localhost:5555"
    @echo "  postgres  127.0.0.1:5434 (db 'sandbox', creds in .envs/.local/.postgres)"
    @echo "  keycloak  http://localhost:8080  (just keycloak — profile-gated, admin/admin)"
    @echo ""

# keycloak: Start the profile-gated local Keycloak.
keycloak:
    @docker compose --profile keycloak up -d keycloak

# check: Everything CI runs, in the same order.
check:
    @docker compose run --rm django ruff check sandbox config tests
    @docker compose run --rm django ruff format --check sandbox config tests
    @docker compose run --rm django mypy sandbox config tests
    @docker compose run --rm django lint-imports
    # --database: without it the DB-level checks (index name length, etc) are skipped.
    @docker compose run --rm django python manage.py check --database default
    @docker compose run --rm django python manage.py makemigrations --check --dry-run
    @docker compose run --rm django pytest --cov --cov-fail-under=85

# build: Build python image.
build *args:
    @echo "Building python image..."
    @docker compose build {{args}}

# resync: Rebuild and pick up dependency changes.
# `build` alone is not enough: /app/.venv is an anonymous volume, so a rebuilt
# image keeps mounting the OLD venv and new packages never appear.
resync *args:
    @echo "Rebuilding and renewing the venv volume..."
    @docker compose build {{args}}
    @docker compose up -d --force-recreate --renew-anon-volumes {{args}}

# up: Start up containers.
up:
    @echo "Starting up containers..."
    @docker compose up -d --remove-orphans

# down: Stop containers.
down:
    @echo "Stopping containers..."
    @docker compose down

# prune: Remove containers and their volumes.
prune *args:
    @echo "Killing containers and removing volumes..."
    @docker compose down -v {{args}}

# logs: View container logs
logs *args:
    @docker compose logs -f {{args}}

# manage: Executes `manage.py` command.
manage +args:
    @docker compose run --rm django python ./manage.py {{args}}

# pytest: Run tests with pytest.
pytest *args:
    @docker compose run --rm django pytest {{args}}
