from django.db import models

from itou.users.enums import KIND_EMPLOYER, KIND_PRESCRIBER


class AdministrativeCriteriaAnnex(models.TextChoices):
    NO_ANNEX = "0", "Aucune annexe associée"
    ANNEX_1 = "1", "Annexe 1"
    ANNEX_2 = "2", "Annexe 2"
    BOTH_ANNEXES = "1+2", "Annexes 1 et 2"


class AdministrativeCriteriaLevel(models.TextChoices):
    LEVEL_1 = "1", "Niveau 1"
    LEVEL_2 = "2", "Niveau 2"


class AdministrativeCriteriaLevelPrefix(models.TextChoices):
    LEVEL_1_PREFIX = "level_1_"
    LEVEL_2_PREFIX = "level_2_"


class AuthorKind(models.TextChoices):
    PRESCRIBER = KIND_PRESCRIBER, "Prescripteur habilité"
    EMPLOYER = KIND_EMPLOYER, "Employeur"
    GEIQ = "geiq", "GEIQ"
