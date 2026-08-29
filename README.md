# ABDM Sandbox

ABDM integrator sandbox portal — v2 rewrite. Plan of record lives in [plan/](plan/) (start at [00-master-plan.md](plan/00-master-plan.md); the v0 pilot cut being built first is §6, with a ticket per work item in [plan/v0-tickets/](plan/v0-tickets/)).

[![Built with Cookiecutter Django](https://img.shields.io/badge/built%20with-Cookiecutter%20Django-ff69b4.svg?logo=cookiecutter)](https://github.com/cookiecutter/cookiecutter-django/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

## Getting started

Everything runs in Docker; no VPN or ABDM credentials are needed for local work.
You need Docker and [`just`](https://github.com/casey/just) — the command runner
cookiecutter-django ships with, in place of a Makefile:

```bash
brew install just          # macOS; see the just README for Linux/Windows
```

Then, from a fresh clone:

```bash
just bootstrap
```

That copies the example env files if you have none, builds, starts every
container, migrates, seeds demo data and prints the URLs. The individual steps,
if you would rather run them yourself:

```bash
cp .envs/.local/.django.example .envs/.local/.django
cp .envs/.local/.postgres.example .envs/.local/.postgres
just build
just up
just manage migrate
just manage seed_sandbox_demo
```

Then open <http://localhost:8000> (emails land in Mailpit at <http://localhost:8025>).
Seeded logins are printed by the seed command. The two env files are per-developer and deliberately untracked — nothing that looks like a credential belongs in this repository.

House rules worth knowing before the first PR:

- **Views never write state.** Writes go through a service function ([01-backend.md](plan/01-backend.md) §1).
- **Styling uses careui**, ported from [ohcnetwork/experience](https://github.com/ohcnetwork/experience): component classes live in `sandbox/static/css/careui.css`, colour comes from semantic tokens (`bg-primary`, `text-muted-foreground`, `border-border`) and never a raw hex. New components land there, not as utility soup in templates. Keep the file byte-compatible with upstream so fixes travel both ways.
- **Forms render through `{% ui_field %}`** (`sandbox/theme/templatetags/careui.py`), which is also how allauth's own forms get styled. There is no crispy.
- **One verification gate** — `VerificationRequiredMiddleware` redirects staff without a TOTP device to MFA setup, and everyone else to OTP verification of email and phone.
- **A DEBUG process cannot talk to shared infrastructure**; `config/settings/guards.py` refuses to boot.

## Working offline

Nothing in local development talks to Keycloak, WSO2, HIE-CM or the notification gateway. Every one of those sits behind a port in `sandbox/integrations/ports.py`, and `local`/`test` resolve each port to an in-process fake (`sandbox/integrations/fakes.py`) via `INTEGRATION_PORTS`. `just up` plus `just manage seed_sandbox_demo` gives a fully navigable portal with no VPN and no ABDM credentials.

Fake state lives in the cache rather than in module globals, so a client created by a Celery task is visible to the web process. Notifications are sent through Django's email backend, which means OTP and lifecycle mail is readable in Mailpit at <http://localhost:8025>.

To rehearse a failure — the `PROVISIONING_FAILED` screen, a retry button, a slow dependency — arm the fakes from `just manage shell`:

```python
from sandbox.integrations import fakes
from sandbox.integrations.ports import ExternalSystem

fakes.fail_next(ExternalSystem.WSO2, "create_application")   # fails once, then clears
fakes.always_fail(ExternalSystem.HIECM, retryable=False)     # until clear_failures()
fakes.set_latency(ExternalSystem.KEYCLOAK, 3.0)              # seconds, every call
fakes.clear_failures(ExternalSystem.HIECM)
fakes.reset_fakes()                                          # drop all fake state
```

Tests reset the fakes automatically (autouse fixture in `sandbox/conftest.py`). To point an environment at a real system instead, set the matching env var to a dotted path — `INTEGRATION_IDP=sandbox.integrations.keycloak.adapter.KeycloakIdpAdmin`.

To exercise the real Keycloak Admin API locally, a profile-gated Keycloak is available on <http://localhost:8080> (`admin`/`admin`):

```bash
docker compose -f docker-compose.local.yml --profile keycloak up -d keycloak
```

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
