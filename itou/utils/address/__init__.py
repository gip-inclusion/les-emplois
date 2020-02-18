from django.conf import settings
from django.utils.translation import gettext_lazy as _

from .departments import DEPARTMENTS


TEST_DEPARTMENTS = [("", "---")] + [
    (d, DEPARTMENTS[d]) for d in settings.ITOU_TEST_DEPARTMENTS
]

TEST_DEPARTMENTS_HELP_TEXT = _(
    (
        "Seuls les départements du Bas-Rhin (67), du Pas-de-Calais (62) "
        "et de la Seine Saint Denis (93) sont disponibles pendant la phase actuelle "
        "d'expérimentation de la plateforme de l'inclusion."
    )
)
