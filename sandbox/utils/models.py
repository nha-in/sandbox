"""Shared abstract base model — (03-database.md §3.1).

Every domain model extends BaseModel: external_id is the only identifier that
ever leaves the system (integer PKs stay internal), and delete() soft-deletes
via the `deleted` flag rather than issuing a DELETE.
"""

from __future__ import annotations

import uuid

from django.db import models


class BaseManager(models.Manager):
    """Default manager — hides soft-deleted rows from every ordinary query."""

    def get_queryset(self):
        return super().get_queryset().filter(deleted=False)


class BaseModel(models.Model):
    external_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_index=True,
    )
    created_date = models.DateTimeField(auto_now_add=True, db_index=True)
    modified_date = models.DateTimeField(auto_now=True, db_index=True)
    deleted = models.BooleanField(default=False)

    all_objects = models.Manager()
    objects = BaseManager()

    class Meta:
        abstract = True
        default_manager_name = "objects"  # pin default regardless of declaration order

    def delete(self, *args, **kwargs):
        self.deleted = True
        self.save(update_fields=["deleted", "modified_date"])
