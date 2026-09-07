"""`is_ohc_team` collapses into `is_staff` (plan 12 §8.4).

The two were deliberately separate — the field's help text said so — but the
distinction bought nothing: every grant set both, and Django's own `is_staff`
already means "may enter the admin", with permissions deciding what is behind
it. Console authority that is finer than the door lives in `ReviewRole`.

Existing OHC accounts are made staff before the column goes, so nobody loses
the console in the migration.
"""

from __future__ import annotations

from django.db import migrations


def promote(apps, schema_editor):
    apps.get_model("users", "User").objects.filter(is_ohc_team=True).update(
        is_staff=True,
    )


class Migration(migrations.Migration):
    dependencies = [("users", "0001_initial")]

    operations = [
        migrations.RunPython(promote, migrations.RunPython.noop),
        migrations.RemoveField(model_name="user", name="is_ohc_team"),
    ]
