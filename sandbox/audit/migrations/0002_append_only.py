"""Audit rows are evidence — see workflow/0002_append_only for the reasoning."""

from django.db import migrations

TABLE = "audit_auditevent"


class Migration(migrations.Migration):
    dependencies = [("audit", "0001_initial")]

    operations = [
        migrations.RunSQL(
            sql=f"REVOKE UPDATE, DELETE ON {TABLE} FROM CURRENT_USER;",
            reverse_sql=f"GRANT UPDATE, DELETE ON {TABLE} TO CURRENT_USER;",
        ),
    ]
