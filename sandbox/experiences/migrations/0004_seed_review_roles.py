"""The three NHA roles the v3 specification names, as data.

They were `RoleDefinition`s in the ABDM registry until plan 12 §5 made review
roles editable. Seeded rather than hard-coded so an administrator can change
them — but seeded, because a portal with no review roles cannot be reviewed.

Permission keys are still code, so this migration names keys the registry
declares; `ReviewRole.clean()` refuses any it does not.
"""

from __future__ import annotations

from django.db import migrations

#: Literals, not imports: a migration must keep meaning even when the key
#: constants are later renamed. These are the sets the three `RoleDefinition`s
#: carried before §10 moved them out of the registry, less MANAGE_REVIEW_ACCESS,
#: which §5.1 retires along with per-application reviewer assignment.
OBSERVER = ("application.view", "queries.view")
REVIEWER = (
    *OBSERVER,
    "application.review",
    "queries.raise",
    "queries.resolve",
)
DECISION_MAKER = (*REVIEWER, "application.approve", "application.reject")

ROLES = [
    (
        "review_observer",
        "Review observer",
        "Reads every application and its history. Changes nothing.",
        OBSERVER,
    ),
    (
        "reviewer",
        "Reviewer",
        "Reviews evidence, asks the applicant questions, verifies documents. "
        "May not approve or reject.",
        REVIEWER,
    ),
    (
        "decision_maker",
        "Decision maker",
        "Everything a reviewer may, plus approving and rejecting.",
        DECISION_MAKER,
    ),
]


def seed(apps, schema_editor):
    ReviewRole = apps.get_model("experiences", "ReviewRole")
    for key, name, description, permissions in ROLES:
        ReviewRole.objects.update_or_create(
            key=key,
            defaults={
                "name": name,
                "description": description,
                "permissions": list(permissions),
            },
        )


def unseed(apps, schema_editor):
    ReviewRole = apps.get_model("experiences", "ReviewRole")
    ReviewRole.objects.filter(key__in=[key for key, *_ in ROLES]).delete()


class Migration(migrations.Migration):
    dependencies = [("experiences", "0003_reviewrole_reviewroleassignment")]
    operations = [migrations.RunPython(seed, unseed)]
