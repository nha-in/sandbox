# ABDM Sandbox

ABDM integrator sandbox portal — v2 rewrite. Plan of record: `../v2-plan-rev2/` (start at `00-master-plan.md`; the pilot cut being built first is `v0-plan.md`).

[![Built with Cookiecutter Django](https://img.shields.io/badge/built%20with-Cookiecutter%20Django-ff69b4.svg?logo=cookiecutter)](https://github.com/cookiecutter/cookiecutter-django/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

## Getting started

Everything runs in Docker; no VPN or ABDM credentials are needed for local work.

```bash
just build
just up
just manage seed_sandbox_demo
```

Then open <http://localhost:8000> (emails land in Mailpit at <http://localhost:8025>).
Seeded logins are printed by the seed command.

House rules worth knowing before the first PR:

- **Views never write state.** Writes go through a service function ([01-backend.md](../v2-plan-rev2/01-backend.md) §1).
- **Styling uses the `ui-*` classes** in `sandbox/static/css/source.css`; new components land there, not as utility soup in templates.
- **Staff accounts require MFA** — `StaffMFARequiredMiddleware` redirects staff without a TOTP device.
- **A DEBUG process cannot talk to shared infrastructure**; `config/settings/guards.py` refuses to boot.

## Quality gates

CI runs pre-commit (ruff, djLint, django-upgrade), mypy, import-linter contracts, `makemigrations --check`, pytest with an 85% coverage floor, gitleaks and Trivy. Run them locally with:

```bash
just pytest
uv run mypy sandbox config
uv run lint-imports
uv run pre-commit run --all-files
```

`release.yml` builds, SBOM-attaches and scans the production image into GHCR. The deploy step is intentionally absent until the hosting target is decided with NHA.

## Settings

Moved to [settings](https://cookiecutter-django.readthedocs.io/en/latest/1-getting-started/settings.html).

## Basic Commands

### Setting Up Your Users

- To create a **normal user account**, just go to Sign Up and fill out the form. Once you submit it, you'll see a "Verify Your E-mail Address" page. Go to your console to see a simulated email verification message. Copy the link into your browser. Now the user's email should be verified and ready to go.

- To create a **superuser account**, use this command:

      uv run python manage.py createsuperuser

For convenience, you can keep your normal user logged in on Chrome and your superuser logged in on Firefox (or similar), so that you can see how the site behaves for both kinds of users.

### Type checks

Running type checks with mypy:

    uv run mypy sandbox

### Test coverage

To run the tests, check your test coverage, and generate an HTML coverage report:

    uv run coverage run -m pytest
    uv run coverage html
    uv run open htmlcov/index.html

#### Running tests with pytest

    uv run pytest

### CSS

Tailwind is compiled by the standalone CLI binary (no node anywhere):

    just manage tailwind build     # one-off
    just manage tailwind watch     # or run the `tailwind` compose service

### Celery

This app comes with Celery.

To run a celery worker:

```bash
cd sandbox
uv run celery -A config.celery_app worker -l info
```

Please note: For Celery's import magic to work, it is important _where_ the celery commands are run. If you are in the same folder with _manage.py_, you should be right.

To run [periodic tasks](https://docs.celeryq.dev/en/stable/userguide/periodic-tasks.html), you'll need to start the celery beat scheduler service. You can start it as a standalone process:

```bash
cd sandbox
uv run celery -A config.celery_app beat
```

or you can embed the beat service inside a worker with the `-B` option (not recommended for production use):

```bash
cd sandbox
uv run celery -A config.celery_app worker -B -l info
```

### Email Server

In development, it is often nice to be able to see emails that are being sent from your application. For that reason local SMTP server [Mailpit](https://github.com/axllent/mailpit) with a web interface is available as docker container.

Container mailpit will start automatically when you will run all docker containers.
Please check [cookiecutter-django Docker documentation](https://cookiecutter-django.readthedocs.io/en/latest/2-local-development/developing-locally-docker.html) for more details how to start all containers.

With Mailpit running, to view messages that are sent by your application, open your browser and go to `http://127.0.0.1:8025`

### Sentry

Sentry is an error logging aggregator service. You can sign up for a free account at <https://sentry.io/signup/?code=cookiecutter> or download and host it yourself.
The system is set up with reasonable defaults, including 404 logging and integration with the WSGI application.

You must set the DSN url in production.

## Deployment

The following details how to deploy this application.

### Docker

See detailed [cookiecutter-django Docker documentation](https://cookiecutter-django.readthedocs.io/en/latest/3-deployment/deployment-with-docker.html).
