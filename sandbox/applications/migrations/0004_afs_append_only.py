"""Submissions are the record: append-only at the database, not by convention.

Like the transition log, but with one column-level exception — superseding a
revision flips the old row's `is_current`, so UPDATE is granted back on that
single column. Also backfills `workflow_key` from `kind` on pre-port rows
(v0 only ever created SANDBOX, which the new registry names ABDM).
"""

from django.db import migrations

TABLE = "applications_applicationformsubmission"

REVOKE = (
    f"REVOKE UPDATE, DELETE ON {TABLE} FROM CURRENT_USER;\n"
    f"GRANT UPDATE (is_current) ON {TABLE} TO CURRENT_USER;"
)
GRANT = f"GRANT UPDATE, DELETE ON {TABLE} TO CURRENT_USER;"

#: old ApplicationKind value -> workflow registry key
KIND_TO_WORKFLOW = {
    "SANDBOX": "ABDM",
    "HCX": "HCX",
    "UHI": "UHI",
    "HIU": "HIU",
    "NHCX": "NHCX",
}


def backfill_workflow_key(apps, schema_editor):
    application_model = apps.get_model("applications", "Application")
    for kind, workflow_key in KIND_TO_WORKFLOW.items():
        application_model.objects.filter(kind=kind, workflow_key="").update(
            workflow_key=workflow_key,
        )


def unfill_workflow_key(apps, schema_editor):
    apps.get_model("applications", "Application").objects.update(workflow_key="")


class Migration(migrations.Migration):
    dependencies = [
        ("applications", "0003_form_submissions_and_workflow_key"),
    ]

    operations = [
        migrations.RunSQL(sql=REVOKE, reverse_sql=GRANT),
        migrations.RunPython(backfill_workflow_key, unfill_workflow_key),
    ]
