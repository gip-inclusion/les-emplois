from django.apps import AppConfig
from django.db import models

from itou.siaes import enums


class SiaesAppConfig(AppConfig):
    name = "itou.siaes"
    verbose_name = "SIAE"

    def ready(self):
        super().ready()
        models.signals.post_migrate.connect(create_pole_emploi_siae, sender=self)


def create_pole_emploi_siae(*args, **kwargs):
    from itou.siaes.models import Siae

    Siae._base_manager.get_or_create(
        siret=enums.POLE_EMPLOI_SIRET,
        defaults={
            "name": "POLE EMPLOI",
            "kind": enums.SIAE_KIND_RESERVED,
            "source": enums.SIAE_SOURCE_ADMIN_CREATED,
        },
    )
