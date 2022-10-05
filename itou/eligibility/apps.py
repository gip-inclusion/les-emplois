import json
import pathlib

from django.apps import AppConfig
from django.conf import settings
from django.db import models, transaction


class EligibilityAppConfig(AppConfig):
    name = "itou.eligibility"

    def ready(self):
        super().ready()
        models.signals.post_migrate.connect(create_administrative_criteria, sender=self)


def create_administrative_criteria(*args, **kwargs):
    from .models import AdministrativeCriteria

    json_path = pathlib.Path(settings.APPS_DIR) / "eligibility/data/administrative_criteria.json"
    with open(json_path, "rb") as fp:
        admin_crits_spec = json.load(fp)
    with transaction.atomic():
        for spec in admin_crits_spec:
            AdministrativeCriteria.objects.update_or_create(
                pk=spec["pk"],
                defaults=spec["fields"],
            )
