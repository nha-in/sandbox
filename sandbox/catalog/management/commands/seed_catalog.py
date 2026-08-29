"""Seed catalog reference data — required in every environment, never destructive.

Unlike `seed_sandbox_demo` (dev/e2e/staging fixture data, DEBUG-gated, has
`--fresh`), this command is safe and expected to run in production: it only
ever adds or updates rows by natural key, and the deploy/setup pipeline is
responsible for invoking it after `migrate` (see compose/*/django/start).
"""

from __future__ import annotations

import json

from django.conf import settings
from django.core.management.base import BaseCommand

from sandbox.catalog.models import Milestone

SEED_FILE = settings.BASE_DIR / "db" / "seeds" / "catalog_milestones.json"


class Command(BaseCommand):
    help = "Seed catalog reference data (idempotent; safe to run in any environment)."

    def handle(self, *args, **options):
        records = json.loads(SEED_FILE.read_text())
        for record in records:
            Milestone.objects.update_or_create(
                key=record["key"],
                defaults={
                    "title": record["title"],
                    "track": record["track"],
                    "order": record["order"],
                    "is_active": record["is_active"],
                },
            )
        self.stdout.write(self.style.SUCCESS(f"Seeded {len(records)} milestones."))
