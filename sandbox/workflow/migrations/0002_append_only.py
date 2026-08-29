"""Make the transition log append-only at the database, not just by convention.

A row saying who approved an application is worthless if the application's own
role can edit it afterwards. Revoking UPDATE and DELETE means a bug, an ORM
mistake or a compromised process cannot rewrite history — only a DBA can, and
that leaves its own trail.
"""

from django.db import migrations

TABLES = ("workflow_workflowtransition",)

REVOKE = "\n".join(
    f"REVOKE UPDATE, DELETE ON {table} FROM CURRENT_USER;" for table in TABLES
)
GRANT = "\n".join(
    f"GRANT UPDATE, DELETE ON {table} TO CURRENT_USER;" for table in TABLES
)


class Migration(migrations.Migration):
    dependencies = [("workflow", "0001_initial")]

    operations = [migrations.RunSQL(sql=REVOKE, reverse_sql=GRANT)]
