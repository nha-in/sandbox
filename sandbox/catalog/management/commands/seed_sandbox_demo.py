"""Seeds a demo dataset so a fresh checkout is navigable without VPN access.

Grows one section per app as the domain lands; every section must stay
idempotent so the command can be re-run against an existing database.
"""

from allauth.account.models import EmailAddress
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.db import transaction

User = get_user_model()

DEMO_PASSWORD = "sandbox-demo-password"  # noqa: S105
DEMO_USERS = [
    (
        "admin@example.com",
        "Sandbox Superuser",
        {"is_staff": True, "is_superuser": True},
    ),
    ("reviewer@example.com", "Sandbox Reviewer", {"is_staff": True}),
    ("integrator@example.com", "Demo Integrator", {}),
]


class Command(BaseCommand):
    help = "Create or refresh the local demo dataset."

    def add_arguments(self, parser):
        parser.add_argument(
            "--fresh",
            action="store_true",
            help="Delete previously seeded demo records before recreating them.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Allow seeding outside DEBUG (staging snapshots).",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG and not options["force"]:
            msg = "Refusing to seed outside DEBUG without --force."
            raise CommandError(msg)

        if options["fresh"]:
            self._purge()

        self._seed_users()
        self.stdout.write(
            self.style.SUCCESS(f"Seeded demo data. Password: {DEMO_PASSWORD}"),
        )

    def _purge(self):
        emails = [email for email, _, _ in DEMO_USERS]
        deleted, _ = User.objects.filter(email__in=emails).delete()
        self.stdout.write(f"Removed {deleted} previously seeded records.")

    def _seed_users(self):
        for email, name, flags in DEMO_USERS:
            user, created = User.objects.get_or_create(
                email=email,
                defaults={"name": name, **flags},
            )
            if created:
                user.set_password(DEMO_PASSWORD)
                user.save(update_fields=["password"])
            EmailAddress.objects.update_or_create(
                user=user,
                email=email,
                defaults={"verified": True, "primary": True},
            )
            self.stdout.write(f"{'created' if created else 'exists '} user {email}")
