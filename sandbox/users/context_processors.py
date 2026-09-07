from django.conf import settings

from .permissions import is_console_user


def allauth_settings(request):
    """Expose some settings from django-allauth in templates."""
    return {
        "ACCOUNT_ALLOW_REGISTRATION": settings.ACCOUNT_ALLOW_REGISTRATION,
    }


def console_user(request):
    """Whether the signed-in user reaches the staff console.

    The app shell reads this to offer the console link, so it has to be
    available on every page rather than passed view by view.
    """
    return {"is_console_user": is_console_user(getattr(request, "user", None))}
