from .base import *  # noqa: F403
from .base import DATABASES
from .base import INSTALLED_APPS
from .base import MIDDLEWARE
from .base import REDIS_URL
from .base import env
from .guards import assert_isolated_local_environment
from .guards import assert_staff_mfa_is_required

# GENERAL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#debug
DEBUG = True
# https://docs.djangoproject.com/en/dev/ref/settings/#secret-key
SECRET_KEY = env(
    "DJANGO_SECRET_KEY",
    default="yzqP8MzqGQwpOGVjQzt0RLkj5LMvHgRbrhoEOTNgLUA9Y0Xy0fxIF6S41LVW6ChK",
)
# https://docs.djangoproject.com/en/dev/ref/settings/#allowed-hosts
ALLOWED_HOSTS = ["localhost", "0.0.0.0", "127.0.0.1"]  # noqa: S104

assert_isolated_local_environment(DEBUG, DATABASES, REDIS_URL)

# EMAIL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#email-host
EMAIL_HOST = env("EMAIL_HOST", default="mailpit")
# https://docs.djangoproject.com/en/dev/ref/settings/#email-port
EMAIL_PORT = 1025

# WhiteNoise
# ------------------------------------------------------------------------------
# http://whitenoise.evans.io/en/latest/django.html#using-whitenoise-in-development
INSTALLED_APPS = ["whitenoise.runserver_nostatic", *INSTALLED_APPS]


# django-debug-toolbar
# ------------------------------------------------------------------------------
# https://django-debug-toolbar.readthedocs.io/en/latest/installation.html#prerequisites
INSTALLED_APPS += ["debug_toolbar"]
# https://django-debug-toolbar.readthedocs.io/en/latest/installation.html#middleware
MIDDLEWARE += ["debug_toolbar.middleware.DebugToolbarMiddleware"]
# https://django-debug-toolbar.readthedocs.io/en/latest/configuration.html#debug-toolbar-config
DEBUG_TOOLBAR_CONFIG = {
    "DISABLE_PANELS": [
        "debug_toolbar.panels.redirects.RedirectsPanel",
        # Disable profiling panel due to an issue with Python 3.12+:
        # https://github.com/jazzband/django-debug-toolbar/issues/1875
        "debug_toolbar.panels.profiling.ProfilingPanel",
    ],
    "SHOW_TEMPLATE_CONTEXT": True,
}
# https://django-debug-toolbar.readthedocs.io/en/latest/installation.html#internal-ips
INTERNAL_IPS = ["127.0.0.1", "10.0.2.2"]
if env("USE_DOCKER") == "yes":
    import socket

    hostname, _, ips = socket.gethostbyname_ex(socket.gethostname())
    INTERNAL_IPS += [".".join([*ip.split(".")[:-1], "1"]) for ip in ips]

# django-extensions
# ------------------------------------------------------------------------------
# https://django-extensions.readthedocs.io/en/latest/installation_instructions.html#configuration
INSTALLED_APPS += ["django_extensions"]
# Celery
# ------------------------------------------------------------------------------

# https://docs.celeryq.dev/en/stable/userguide/configuration.html#task-eager-propagates
CELERY_TASK_EAGER_PROPAGATES = True

# Integrations
# ------------------------------------------------------------------------------
# Base leaves this empty so a real environment fails loudly rather than
# subscribing an integrator to invented APIs — the published names are NHA's to
# supply (open question 4). Locally every port is a fake that does not care what
# the names are, and without something here the provisioning chain fails at WSO2
# on every dev machine, which made both B7's happy path and C7's panel
# unreachable without knowing to set an env var nobody had written down.
WSO2_API_NAMES = {
    "ABDM": tuple(
        env.list("WSO2_SANDBOX_API_NAMES", default=["HealthIdAPI", "GatewayAPI"]),
    ),
}

# Staff sign in without an authenticator app here. `guards.py` refuses to boot
# any settings module that does this with DEBUG off.
STAFF_MFA_REQUIRED = env.bool("STAFF_MFA_REQUIRED", default=False)
assert_staff_mfa_is_required(DEBUG, STAFF_MFA_REQUIRED)
# Your stuff...
# ------------------------------------------------------------------------------
