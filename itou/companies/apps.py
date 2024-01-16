from django.apps import AppConfig
from django.db import models

from itou.companies import enums


class CompaniesAppConfig(AppConfig):
    name = "itou.companies"
    verbose_name = "Entreprises"

    def ready(self):
        super().ready()
        models.signals.post_migrate.connect(create_pole_emploi_company, sender=self)


def create_pole_emploi_company(*args, **kwargs):
    from itou.companies.models import Company

    Company._base_manager.get_or_create(
        siret=enums.POLE_EMPLOI_SIRET,
        defaults={
            "name": "France Travail",
            "kind": enums.COMPANY_KIND_RESERVED,
            "source": enums.COMPANY_SOURCE_ADMIN_CREATED,
        },
    )
