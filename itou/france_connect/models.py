import datetime

from django.db import models
from django.utils import timezone


class FranceConnectQuerySet(models.QuerySet):
    def cleanup(self):
        return self.filter(created_at__lte=timezone.now() - datetime.timedelta(hours=1)).delete()


class FranceConnectState(models.Model):
    created_at = models.DateTimeField(default=timezone.now)
    # Length used in call to get_random_string()
    csrf = models.CharField(max_length=12, blank=False, null=False, unique=True)

    objects = models.Manager.from_queryset(FranceConnectQuerySet)()
