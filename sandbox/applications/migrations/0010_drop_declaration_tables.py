"""Drop the declaration tables.

Milestone claims and exit bundles are form submissions now
(`applications.ApplicationFormSubmission` + `ApplicationDocument`), so these
three tables have no writer left. The app is gone, so the delete lives here.

Pre-release: no production data is being discarded.
"""

from __future__ import annotations

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("applications", "0009_trim_application_states"),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                "DROP TABLE IF EXISTS declarations_declarationdocument CASCADE",
                "DROP TABLE IF EXISTS declarations_declarationmilestone CASCADE",
                "DROP TABLE IF EXISTS declarations_declaration CASCADE",
                "DELETE FROM django_migrations WHERE app = 'declarations'",
            ],
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
