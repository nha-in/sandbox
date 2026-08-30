"""
With these settings, tests run faster.
"""

from .base import *  # noqa: F403
from .base import STORAGES
from .base import TEMPLATES
from .base import env

# GENERAL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#secret-key
SECRET_KEY = env(
    "DJANGO_SECRET_KEY",
    default="UpfboThuoZxhs0SeQzgylz6P4zOWzJ9zt1JcCtkxPFKWRI5TRJdGZRoKMAYRdX6c",
)
# https://docs.djangoproject.com/en/dev/ref/settings/#test-runner
TEST_RUNNER = "django.test.runner.DiscoverRunner"

# CACHES
# ------------------------------------------------------------------------------
# Tests must not require a Redis server; sessions ride on this cache too.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "",
    },
}

# PASSWORDS
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#password-hashers
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# EMAIL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#email-backend
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# CELERY
# ------------------------------------------------------------------------------
# Tests must not require a broker. Eager runs the task in-process; propagating
# means a `retry()` surfaces as `celery.exceptions.Retry` instead of vanishing.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# DEBUGGING FOR TEMPLATES
# ------------------------------------------------------------------------------
TEMPLATES[0]["OPTIONS"]["debug"] = True  # type: ignore[index]

# MEDIA
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#media-url
MEDIA_URL = "http://media.testserver/"

# UPLOADS
# ------------------------------------------------------------------------------
# The declarations bucket stays an S3 backend so presigning is exercised for
# real; `moto` stands in for the service (see declarations/tests/conftest.py).
# Credentials are deliberately fake so a misconfigured run cannot reach AWS.
STORAGES["declarations"]["OPTIONS"] |= {  # type: ignore[index]
    "endpoint_url": None,  # standard AWS URLs, which moto intercepts
    "access_key": "testing",
    "secret_key": "testing",
}
# Your stuff...
# ------------------------------------------------------------------------------
