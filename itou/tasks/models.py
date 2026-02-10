from django.db import models
from django.utils import timezone


class Task(models.Model):
    data = models.BinaryField()
    priority = models.BigIntegerField(
        blank=True,
        null=True,
        verbose_name="priorité",
    )

    created_at = models.DateTimeField(
        default=timezone.now,
        verbose_name="date de création",
    )

    class Meta:
        indexes = [
            models.Index("created_at", name="created_at_idx"),
            models.Index(
                "priority",
                condition=models.Q(priority__isnull=False),
                name="priority_not_null_idx",
            ),
        ]
