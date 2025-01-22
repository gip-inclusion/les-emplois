import json
import pathlib

from django.apps import AppConfig
from django.conf import settings
from django.db import models, transaction


class EligibilityAppConfig(AppConfig):
    name = "itou.eligibility"
    verbose_name = "Eligibilité"

    def ready(self):
        super().ready()
        models.signals.post_migrate.connect(create_administrative_criteria, sender=self)


def create_administrative_criteria(*args, **kwargs):
    from itou.eligibility.models import AdministrativeCriteria, GEIQAdministrativeCriteria

    to_load = (
        (AdministrativeCriteria, "administrative_criteria.json"),
        (GEIQAdministrativeCriteria, "administrative_criteria_geiq.json"),
    )
    for cls, filename in to_load:
        json_path = pathlib.Path(settings.APPS_DIR) / "eligibility/data" / filename
        with open(json_path, "rb") as fp:
            admin_crits_spec = json.load(fp)
        with transaction.atomic():
            for spec in admin_crits_spec:
                cls.objects.update_or_create(
                    pk=spec["pk"],
                    defaults=spec["fields"],
                )
