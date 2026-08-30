# ruff: noqa: ERA001, E501
"""Base settings to build other settings files upon."""

import os
import ssl
from pathlib import Path

import environ

from .guards import assert_isolated_local_environment
from .guards import assert_staff_mfa_is_required

BASE_DIR = Path(__file__).resolve(strict=True).parent.parent.parent
# sandbox/
APPS_DIR = BASE_DIR / "sandbox"
env = environ.Env()

READ_DOT_ENV_FILE = env.bool("DJANGO_READ_DOT_ENV_FILE", default=False)
if READ_DOT_ENV_FILE:
    # OS environment variables take precedence over variables from .env
    env.read_env(str(BASE_DIR / ".env"))

# GENERAL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#debug
DEBUG = env.bool("DJANGO_DEBUG", False)
# Local time zone. Choices are
# http://en.wikipedia.org/wiki/List_of_tz_zones_by_name
# though not all of them may be available with every OS.
# In Windows, this must be set to your system time zone.
TIME_ZONE = "Asia/Kolkata"
# https://docs.djangoproject.com/en/dev/ref/settings/#language-code
LANGUAGE_CODE = "en-us"
# https://docs.djangoproject.com/en/dev/ref/settings/#languages
# from django.utils.translation import gettext_lazy as _
# LANGUAGES = [
#     ('en', _('English')),
#     ('fr-fr', _('French')),
#     ('pt-br', _('Portuguese')),
# ]
# https://docs.djangoproject.com/en/dev/ref/settings/#site-id
SITE_ID = 1
# https://docs.djangoproject.com/en/dev/ref/settings/#use-i18n
USE_I18N = True
# https://docs.djangoproject.com/en/dev/ref/settings/#use-tz
USE_TZ = True
# https://docs.djangoproject.com/en/dev/ref/settings/#locale-paths
LOCALE_PATHS = [str(BASE_DIR / "locale")]

# DATABASES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#databases

if os.getenv("DATABASE_URL", default=None):
    DATABASES = {"default": env.db("DATABASE_URL")}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env.str("POSTGRES_DB"),
            "USER": env.str("POSTGRES_USER"),
            "PASSWORD": env.str("POSTGRES_PASSWORD"),
            "HOST": env.str("POSTGRES_HOST", default="postgres"),
            "PORT": env.str("POSTGRES_PORT", default="5432"),
        },
    }

DATABASES["default"]["ATOMIC_REQUESTS"] = True
# https://docs.djangoproject.com/en/stable/ref/settings/#std:setting-DEFAULT_AUTO_FIELD

# URLS
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#root-urlconf
ROOT_URLCONF = "config.urls"
# https://docs.djangoproject.com/en/dev/ref/settings/#wsgi-application
WSGI_APPLICATION = "config.wsgi.application"

# APPS
# ------------------------------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.sites",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # "django.contrib.humanize", # Handy template tags
    "django.contrib.admin",
    "django.contrib.postgres",  # required by audit's BrinIndex
    "django.forms",
]
THIRD_PARTY_APPS = [
    "allauth",
    "allauth.account",
    "allauth.mfa",
    "allauth.socialaccount",
    "django_celery_beat",
    "django_htmx",
    "django_tailwind_cli",
]

LOCAL_APPS = [
    "sandbox.theme",
    "sandbox.users",
    "sandbox.organisations",
    "sandbox.catalog",
    "sandbox.applications",
    "sandbox.declarations",
    "sandbox.workflow",
    "sandbox.audit",
    "sandbox.integrations",
    "sandbox.notifications",
    "sandbox.console",
]
# https://docs.djangoproject.com/en/dev/ref/settings/#installed-apps
INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# MIGRATIONS
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#migration-modules
MIGRATION_MODULES = {"sites": "sandbox.contrib.sites.migrations"}

# AUTHENTICATION
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#authentication-backends
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]
# https://docs.djangoproject.com/en/dev/ref/settings/#auth-user-model
AUTH_USER_MODEL = "users.User"
# https://docs.djangoproject.com/en/dev/ref/settings/#login-redirect-url
LOGIN_REDIRECT_URL = "users:redirect"
# https://docs.djangoproject.com/en/dev/ref/settings/#login-url
LOGIN_URL = "account_login"

# PASSWORDS
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#password-hashers
PASSWORD_HASHERS = [
    # https://docs.djangoproject.com/en/dev/topics/auth/passwords/#using-argon2-with-django
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
]
# https://docs.djangoproject.com/en/dev/ref/settings/#auth-password-validators
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# MIDDLEWARE
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#middleware
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "sandbox.users.middleware.VerificationRequiredMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
]

# STATIC
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#static-root
STATIC_ROOT = str(BASE_DIR / "staticfiles")
# https://docs.djangoproject.com/en/dev/ref/settings/#static-url
STATIC_URL = "/static/"
# https://docs.djangoproject.com/en/dev/ref/contrib/staticfiles/#std:setting-STATICFILES_DIRS
STATICFILES_DIRS = [str(APPS_DIR / "static")]
# https://docs.djangoproject.com/en/dev/ref/contrib/staticfiles/#staticfiles-finders
STATICFILES_FINDERS = [
    "django.contrib.staticfiles.finders.FileSystemFinder",
    "django.contrib.staticfiles.finders.AppDirectoriesFinder",
]

# MEDIA
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#media-root
MEDIA_ROOT = str(APPS_DIR / "media")
# https://docs.djangoproject.com/en/dev/ref/settings/#media-url
MEDIA_URL = "/media/"

# TEMPLATES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#templates
TEMPLATES = [
    {
        # https://docs.djangoproject.com/en/dev/ref/settings/#std:setting-TEMPLATES-BACKEND
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # https://docs.djangoproject.com/en/dev/ref/settings/#dirs
        "DIRS": [str(APPS_DIR / "templates")],
        # https://docs.djangoproject.com/en/dev/ref/settings/#app-dirs
        "APP_DIRS": True,
        "OPTIONS": {
            # https://docs.djangoproject.com/en/dev/ref/settings/#template-context-processors
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.template.context_processors.i18n",
                "django.template.context_processors.media",
                "django.template.context_processors.static",
                "django.template.context_processors.tz",
                "django.contrib.messages.context_processors.messages",
                "sandbox.users.context_processors.allauth_settings",
                "sandbox.organisations.context_processors.active_organisation",
                "sandbox.organisations.context_processors.navigation",
            ],
        },
    },
]

# https://docs.djangoproject.com/en/dev/ref/settings/#form-renderer
FORM_RENDERER = "django.forms.renderers.TemplatesSetting"

# TAILWIND
# ------------------------------------------------------------------------------
# Standalone CLI binary: no node toolchain in any image.
TAILWIND_CLI_VERSION = env("TAILWIND_CLI_VERSION", default="4.3.3")
TAILWIND_CLI_PATH = str(BASE_DIR / ".django_tailwind_cli")
TAILWIND_CLI_SRC_CSS = str(APPS_DIR / "static" / "css" / "source.css")
TAILWIND_CLI_DIST_CSS = "css/tailwind.css"

# FIXTURES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#fixture-dirs
FIXTURE_DIRS = (str(APPS_DIR / "fixtures"),)

# SECURITY
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#session-cookie-httponly
SESSION_COOKIE_HTTPONLY = True
# https://docs.djangoproject.com/en/dev/ref/settings/#csrf-cookie-httponly
CSRF_COOKIE_HTTPONLY = True
# https://docs.djangoproject.com/en/dev/ref/settings/#x-frame-options
X_FRAME_OPTIONS = "DENY"

# EMAIL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#email-backend
EMAIL_BACKEND = env(
    "DJANGO_EMAIL_BACKEND",
    default="django.core.mail.backends.smtp.EmailBackend",
)
# https://docs.djangoproject.com/en/dev/ref/settings/#email-timeout
EMAIL_TIMEOUT = 5

# ADMIN
# ------------------------------------------------------------------------------
# Django Admin URL.
ADMIN_URL = "admin/"
# https://docs.djangoproject.com/en/dev/ref/settings/#admins
ADMINS = ['"ABDM Sandbox Team" <sandbox@abdm.gov.in>']
# https://docs.djangoproject.com/en/dev/ref/settings/#managers
MANAGERS = ADMINS
# https://cookiecutter-django.readthedocs.io/en/latest/settings.html#other-environment-settings
# Force the `admin` sign in process to go through the `django-allauth` workflow
DJANGO_ADMIN_FORCE_ALLAUTH = env.bool("DJANGO_ADMIN_FORCE_ALLAUTH", default=False)

# LOGGING
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#logging
# See https://docs.djangoproject.com/en/dev/topics/logging for
# more details on how to customize your logging configuration.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "%(levelname)s %(asctime)s %(module)s %(process)d %(thread)d %(message)s",
        },
    },
    "handlers": {
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {"level": "INFO", "handlers": ["console"]},
    "loggers": {
        # httpx logs a full URL per request; our own structured line is the record
        # of truth and keeps identifiers out of the message.
        "httpx": {"level": "WARNING"},
        "httpcore": {"level": "WARNING"},
    },
}

REDIS_URL = env("REDIS_URL", default="redis://redis:6379/0")
REDIS_SSL = REDIS_URL.startswith("rediss://")

# CACHES & SESSIONS
# ------------------------------------------------------------------------------
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
    },
}
# Sessions live in Redis; losing Redis logs everyone out rather than silently
# serving stale sessions, so exceptions are deliberately not ignored above.
SESSION_ENGINE = "django.contrib.sessions.backends.cache"

# Celery
# ------------------------------------------------------------------------------
if USE_TZ:
    # https://docs.celeryq.dev/en/stable/userguide/configuration.html#std:setting-timezone
    CELERY_TIMEZONE = TIME_ZONE
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#std:setting-broker_url
CELERY_BROKER_URL = REDIS_URL
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#redis-backend-use-ssl
CELERY_BROKER_USE_SSL = {"ssl_cert_reqs": ssl.CERT_NONE} if REDIS_SSL else None
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#std:setting-result_backend
CELERY_RESULT_BACKEND = REDIS_URL
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#redis-backend-use-ssl
CELERY_REDIS_BACKEND_USE_SSL = CELERY_BROKER_USE_SSL
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#result-extended
CELERY_RESULT_EXTENDED = True
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#result-backend-always-retry
# https://github.com/celery/celery/pull/6122
CELERY_RESULT_BACKEND_ALWAYS_RETRY = True
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#result-backend-max-retries
CELERY_RESULT_BACKEND_MAX_RETRIES = 10
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#std:setting-accept_content
CELERY_ACCEPT_CONTENT = ["json"]
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#std:setting-task_serializer
CELERY_TASK_SERIALIZER = "json"
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#std:setting-result_serializer
CELERY_RESULT_SERIALIZER = "json"
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#task-time-limit
# TODO: set to whatever value is adequate in your circumstances
CELERY_TASK_TIME_LIMIT = 5 * 60
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#task-soft-time-limit
# TODO: set to whatever value is adequate in your circumstances
CELERY_TASK_SOFT_TIME_LIMIT = 60
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#beat-scheduler
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#worker-send-task-events
CELERY_WORKER_SEND_TASK_EVENTS = True
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#std-setting-task_send_sent_event
CELERY_TASK_SEND_SENT_EVENT = True
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#worker-hijack-root-logger
CELERY_WORKER_HIJACK_ROOT_LOGGER = False
# django-allauth
# ------------------------------------------------------------------------------
ACCOUNT_ALLOW_REGISTRATION = env.bool("DJANGO_ACCOUNT_ALLOW_REGISTRATION", True)
# https://docs.allauth.org/en/latest/account/configuration.html
ACCOUNT_LOGIN_METHODS = {"email"}
# https://docs.allauth.org/en/latest/account/configuration.html
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
# https://docs.allauth.org/en/latest/account/configuration.html
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
# A4's OTP is the contact-verification flow, so allauth must not also send a
# confirmation link — two mechanisms for one fact.
ACCOUNT_EMAIL_VERIFICATION = "none"
# One address per account: `users_user.email` is unique and is the login
# identity, and allauth rewrites it when a new address is made primary.
ACCOUNT_MAX_EMAIL_ADDRESSES = 1
# https://docs.allauth.org/en/latest/account/configuration.html
ACCOUNT_ADAPTER = "sandbox.users.adapters.AccountAdapter"
# https://docs.allauth.org/en/latest/account/forms.html
ACCOUNT_FORMS = {"signup": "sandbox.users.forms.UserSignupForm"}
# https://docs.allauth.org/en/latest/socialaccount/configuration.html
SOCIALACCOUNT_ADAPTER = "sandbox.users.adapters.SocialAccountAdapter"
# https://docs.allauth.org/en/latest/socialaccount/configuration.html
SOCIALACCOUNT_FORMS = {"signup": "sandbox.users.forms.UserSocialSignupForm"}

# INTEGRATIONS
# ------------------------------------------------------------------------------
# Each port resolves to a real adapter (B3-B6) or a fake (B2). Defaults are the
# fakes so a laptop with no VPN runs the whole portal; deployments override.
INTEGRATION_PORTS = {
    "IDP": env.str(
        "INTEGRATION_IDP",
        default="sandbox.integrations.fakes.FakeIdpAdmin",
    ),
    "API_GATEWAY": env.str(
        "INTEGRATION_API_GATEWAY",
        default="sandbox.integrations.fakes.FakeApiGateway",
    ),
    "BRIDGE_REGISTRY": env.str(
        "INTEGRATION_BRIDGE_REGISTRY",
        default="sandbox.integrations.fakes.FakeBridgeRegistry",
    ),
    "NOTIFICATION": env.str(
        "INTEGRATION_NOTIFICATION",
        default="sandbox.integrations.fakes.FakeNotificationGateway",
    ),
}

# KEYCLOAK (B3)
# ------------------------------------------------------------------------------
# Issues the integrator's machine credentials. The local realm
# (compose/local/keycloak/) stands in for ABDM's; a real sandbox-tier service
# account is still outstanding (00-master-plan.md open question 4).
KEYCLOAK_BASE_URL = env.str("KEYCLOAK_BASE_URL", default="http://keycloak:8080")
KEYCLOAK_REALM = env.str("KEYCLOAK_REALM", default="abdm-sandbox")
KEYCLOAK_CLIENT_ID = env.str("KEYCLOAK_CLIENT_ID", default="sandbox-provisioner")
KEYCLOAK_CLIENT_SECRET = env.str("KEYCLOAK_CLIENT_SECRET", default="")
# Role NAMES per application kind — never realm UUIDs, which legacy hardcoded.
# This subset is provisional: legacy granted all 14 roles to everyone, and NHA
# has not yet confirmed the per-kind set (open question 4).
KEYCLOAK_ROLE_NAMES = {
    "SANDBOX": tuple(
        env.list(
            "KEYCLOAK_SANDBOX_ROLE_NAMES",
            default=["healthId", "hip", "hiu", "hfr"],
        ),
    ),
}

# WSO2 (B4)
# ------------------------------------------------------------------------------
# The API gateway an integrator's credentials actually pass through. TLS is
# verified by the shared client; legacy disabled it on every WSO2 call.
WSO2_BASE_URL = env.str("WSO2_BASE_URL", default="https://wso2.invalid")
# Legacy talked to ABDM's instance over devportal v2.1; v3 is current. Confirm
# against the real gateway before staging sign-off.
WSO2_DEVPORTAL_PATH = env.str("WSO2_DEVPORTAL_PATH", default="/api/am/devportal/v3")
WSO2_TOKEN_PATH = env.str("WSO2_TOKEN_PATH", default="/oauth2/token")
WSO2_CLIENT_ID = env.str("WSO2_CLIENT_ID", default="")
WSO2_CLIENT_SECRET = env.str("WSO2_CLIENT_SECRET", default="")
WSO2_USERNAME = env.str("WSO2_USERNAME", default="")
WSO2_PASSWORD = env.str("WSO2_PASSWORD", default="")
WSO2_GRANT_TYPE = env.str("WSO2_GRANT_TYPE", default="password")
WSO2_SCOPES = tuple(
    env.list(
        "WSO2_SCOPES",
        default=["apim:subscribe", "apim:app_manage", "apim:sub_manage"],
    ),
)
WSO2_THROTTLING_POLICY = env.str("WSO2_THROTTLING_POLICY", default="Unlimited")
WSO2_TOKEN_TYPE = env.str("WSO2_TOKEN_TYPE", default="JWT")
WSO2_KEY_MANAGER = env.str("WSO2_KEY_MANAGER", default="Resident Key Manager")
WSO2_KEY_TYPE = env.str("WSO2_KEY_TYPE", default="PRODUCTION")
WSO2_READ_TIMEOUT_SECONDS = env.float("WSO2_READ_TIMEOUT_SECONDS", default=15.0)
# API NAMES, never ids. No default: NHA has not published the sandbox API names,
# and a wrong or empty guess would fail silently at provisioning time.
WSO2_API_NAMES = {"SANDBOX": tuple(env.list("WSO2_SANDBOX_API_NAMES", default=[]))}

# How long a secret parked for `map_keys` stays readable (B7 → B4 hand-off).
SECRET_REF_TTL_SECONDS = env.int("SECRET_REF_TTL_SECONDS", default=900)

# HIE-CM (B5)
# ------------------------------------------------------------------------------
# The bridge registry. Internal base URL only — the external `/sandbox/v3/v1/*`
# rewrite is IaC-owned (07-infra-cicd.md §5) and must never appear here.
HIECM_BASE_URL = env.str("HIECM_BASE_URL", default="https://hiecm.invalid")
HIECM_API_PATH = env.str("HIECM_API_PATH", default="/api/v3")
HIECM_SESSION_PATH = env.str("HIECM_SESSION_PATH", default="/sessions")
HIECM_CLIENT_ID = env.str("HIECM_CLIENT_ID", default="")
HIECM_CLIENT_SECRET = env.str("HIECM_CLIENT_SECRET", default="")
HIECM_CM_ID = env.str("HIECM_CM_ID", default="sbx")
# Where HIE-CM delivers an integrator's gateway callbacks. A per-application
# placeholder on a base we control until P4's `applications_callback` collects
# the integrator's real endpoint; legacy pointed every bridge at one hardcoded
# webhook.site bin. `.invalid` by default so an unconfigured deployment cannot
# quietly publish somebody else's host.
HIECM_BRIDGE_CALLBACK_BASE_URL = env.str(
    "HIECM_BRIDGE_CALLBACK_BASE_URL",
    default="https://bridge.invalid",
)

# PROVISIONING CHAIN (B7)
# ------------------------------------------------------------------------------
# ~30 minutes across five attempts (120s doubling, capped at 15m). The ledger,
# not this policy, is what makes a retry safe.
PROVISIONING_MAX_ATTEMPTS = env.int("PROVISIONING_MAX_ATTEMPTS", default=5)
PROVISIONING_RETRY_BACKOFF_SECONDS = env.int(
    "PROVISIONING_RETRY_BACKOFF_SECONDS",
    default=120,
)
PROVISIONING_RETRY_BACKOFF_MAX_SECONDS = env.int(
    "PROVISIONING_RETRY_BACKOFF_MAX_SECONDS",
    default=900,
)
# Bounded: the detail lands on a transition comment a reviewer reads.
PROVISIONING_DETAIL_MAX_CHARS = 500

# NOTIFICATIONS (B6)
# ------------------------------------------------------------------------------
# ABDM's notification service. Internal, unauthenticated on the cluster, which is
# how legacy's Feign client reached it (`NotificationFClient`).
NOTIFICATION_BASE_URL = env.str(
    "NOTIFICATION_BASE_URL",
    default="https://notify.invalid",
)
NOTIFICATION_MESSAGE_PATH = env.str(
    "NOTIFICATION_MESSAGE_PATH",
    default="/internal/v3/notification/message",
)
NOTIFICATION_ORIGIN = env.str("NOTIFICATION_ORIGIN", default="sandbox")
NOTIFICATION_SENDER = env.str("NOTIFICATION_SENDER", default="ABDM Sandbox")
NOTIFICATION_READ_TIMEOUT_SECONDS = env.float(
    "NOTIFICATION_READ_TIMEOUT_SECONDS",
    default=5.0,
)
# Template key -> the provider's template id. Legacy carried the same six as
# `template-id.*` properties; NHA has not yet given us the ids for our tenant, so
# a key with no id fails loudly at send time rather than mailing a blank body.
NOTIFICATION_TEMPLATE_IDS = {
    "send-otp": env.str("NOTIFICATION_TEMPLATE_SEND_OTP", default=""),
    "sandbox-approved": env.str("NOTIFICATION_TEMPLATE_SANDBOX_APPROVED", default=""),
    "sandbox-rejected": env.str("NOTIFICATION_TEMPLATE_SANDBOX_REJECTED", default=""),
    "exit-sent-back": env.str("NOTIFICATION_TEMPLATE_EXIT_SENT_BACK", default=""),
    "exit-rejected": env.str("NOTIFICATION_TEMPLATE_EXIT_REJECTED", default=""),
    "production-approved": env.str(
        "NOTIFICATION_TEMPLATE_PRODUCTION_APPROVED",
        default="",
    ),
}
# Carried verbatim from SandboxConstant's *_MAIL_SUBJECT constants, minus the
# trailing colons legacy left dangling on the production ones.
NOTIFICATION_SUBJECTS = {
    "send-otp": "Sandbox: Email Verification OTP",
    "sandbox-approved": "Application Approved: ABDM Sandbox Integration",
    "sandbox-rejected": "ABDM Sandbox Application: Rejected",
    "exit-sent-back": "ABDM Sandbox Application: Sent Back",
    "exit-rejected": "ABDM Sandbox Application: Exit Rejected",
    "production-approved": (
        "ABDM Application Approved: Eligible to move to Production Environment"
    ),
}
# Delivery retries. `attempts` on the row is the bound, not Celery's max_retries.
NOTIFICATION_MAX_ATTEMPTS = env.int("NOTIFICATION_MAX_ATTEMPTS", default=5)
NOTIFICATION_RETRY_BACKOFF_SECONDS = env.int(
    "NOTIFICATION_RETRY_BACKOFF_SECONDS",
    default=10,
)
NOTIFICATION_RETRY_BACKOFF_MAX_SECONDS = env.int(
    "NOTIFICATION_RETRY_BACKOFF_MAX_SECONDS",
    default=600,
)
# Bounded so a verbose upstream error cannot bloat the log table.
NOTIFICATION_ERROR_MAX_CHARS = 2000
# Where an approval email points. C7's show-once panel takes this over; the
# approval mail must never carry the credentials themselves.
NOTIFICATION_PORTAL_BASE_URL = env.str(
    "NOTIFICATION_PORTAL_BASE_URL",
    default="http://localhost:8000",
)
NOTIFICATION_CREDENTIALS_ROUTE = env.str(
    "NOTIFICATION_CREDENTIALS_ROUTE",
    default="applications:step_review",
)

# FAKES (B2)
# ------------------------------------------------------------------------------
# What the fake realm contains, so `FakeIdpAdmin` 404s an unknown role name the
# way a real Keycloak does. Mirrors compose/local/keycloak/realm-abdm-sandbox.json;
# a role in KEYCLOAK_ROLE_NAMES but not here is a misconfiguration, and the point
# is that it fails offline rather than on first contact with staging.
FAKE_KEYCLOAK_REALM_ROLES = env.list(
    "FAKE_KEYCLOAK_REALM_ROLES",
    default=[
        "bridge",
        "hip",
        "hiu",
        "healthId",
        "health_locker",
        "phr",
        "hfr",
        "hp_id",
        "OIDC",
        "HidAbhaSearch",
        "DIGI_DOCTOR",
        "HIP_PAYER",
        "HIU_PAYER",
    ],
)

# OTP
# ------------------------------------------------------------------------------
# Carried from legacy `OtpServiceImpl` / `SandboxConstant`: OTP_VALIDITY_MINUTES=10,
# MAX_RESEND_ATTEMPTS=5, MAX_WRONG_ATTEMPTS=5, and RESEND_COOLDOWN_SECONDS=90000 —
# which is milliseconds despite the name, so 90 seconds.
OTP_TTL_SECONDS = env.int("OTP_TTL_SECONDS", default=600)
OTP_MAX_ATTEMPTS = env.int("OTP_MAX_ATTEMPTS", default=5)
OTP_ISSUE_MAX = env.int("OTP_ISSUE_MAX", default=5)
OTP_ISSUE_WINDOW_SECONDS = env.int("OTP_ISSUE_WINDOW_SECONDS", default=600)
OTP_RESEND_COOLDOWN_SECONDS = env.int("OTP_RESEND_COOLDOWN_SECONDS", default=90)

# UPLOADS
# ------------------------------------------------------------------------------
# Legacy accepted the same four types but checked only the filename extension
# (`GeneralUtils.isFileTypeSupported`), and its per-file cap was `800 * 3024` —
# a typo for 1024. We keep the formats, sniff the content, and pick round caps.
UPLOAD_MAX_BYTES = env.int("UPLOAD_MAX_BYTES", default=10 * 1024 * 1024)
UPLOAD_MAX_FILES = env.int("UPLOAD_MAX_FILES", default=10)
UPLOAD_MAX_TOTAL_BYTES = env.int(
    "UPLOAD_MAX_TOTAL_BYTES",
    default=30 * 1024 * 1024,
)
UPLOAD_ALLOWED_EXTENSIONS = [".pdf", ".xls", ".xlsx", ".csv"]
#: how long a download link stays valid; short because links get pasted around
UPLOAD_DOWNLOAD_URL_TTL_SECONDS = env.int(
    "UPLOAD_DOWNLOAD_URL_TTL_SECONDS",
    default=300,
)

# STORAGES
# ------------------------------------------------------------------------------
# Declaration documents live in their own private bucket, never `default`:
# nothing in the portal may serve them by URL, only the presigned-download view.
AWS_S3_ENDPOINT_URL = env.str("AWS_S3_ENDPOINT_URL", default="http://minio:9000")
AWS_ACCESS_KEY_ID = env.str("AWS_ACCESS_KEY_ID", default="sandbox")
AWS_SECRET_ACCESS_KEY = env.str("AWS_SECRET_ACCESS_KEY", default="sandbox-secret")
AWS_STORAGE_BUCKET_NAME = env.str("AWS_STORAGE_BUCKET_NAME", default="sandbox-uploads")
AWS_S3_REGION_NAME = env.str("AWS_S3_REGION_NAME", default="us-east-1")

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
    "declarations": {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": AWS_STORAGE_BUCKET_NAME,
            "endpoint_url": AWS_S3_ENDPOINT_URL,
            "region_name": AWS_S3_REGION_NAME,
            "access_key": AWS_ACCESS_KEY_ID,
            "secret_key": AWS_SECRET_ACCESS_KEY,
            "default_acl": "private",
            "querystring_auth": True,  # url() presigns
            "querystring_expire": UPLOAD_DOWNLOAD_URL_TTL_SECONDS,
            "file_overwrite": False,
            "addressing_style": "path",  # MinIO has no virtual-host DNS
            "signature_version": "s3v4",  # botocore still defaults to v2 here
        },
    },
}


# Your stuff...
# ------------------------------------------------------------------------------
#: Deliberately not read from the environment: a control this important should
#: take a code change to remove, not a stray variable. `local.py` turns it off.
STAFF_MFA_REQUIRED = True

assert_isolated_local_environment(DEBUG, DATABASES, REDIS_URL)
assert_staff_mfa_is_required(DEBUG, STAFF_MFA_REQUIRED)
