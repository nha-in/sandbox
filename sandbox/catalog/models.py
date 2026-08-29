"""Catalog: reference data the portal owns (milestones) and reads (LGD)."""

from __future__ import annotations

from django.db import models

from sandbox.utils.models import BaseModel


class Milestone(BaseModel):
    """A sandbox progress milestone integrators self-declare against (A7)."""

    key = models.SlugField(max_length=50)
    title = models.CharField(max_length=200)
    track = models.CharField(max_length=50)
    order = models.PositiveIntegerField()
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["track", "order"]
        constraints = [
            models.UniqueConstraint(
                fields=["key"],
                condition=models.Q(deleted=False),
                name="catalog_milestone_unique_key",
            ),
        ]

    def __str__(self) -> str:
        return self.title
