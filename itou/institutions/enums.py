from django.db import models


class InstitutionKind(models.TextChoices):
    # DDETS_GEIQ coming soon.
    DDETS_IAE = (
        "DDETS IAE",
        "Direction départementale de l'emploi, du travail et des solidarités, division IAE",
    )
    DDETS_LOG = (
        "DDETS LOG",
        "Direction départementale de l'emploi, du travail et des solidarités, division logement insertion",
    )

    # DREETS_GEIQ coming soon.
    DREETS_IAE = (
        "DREETS IAE",
        "Direction régionale de l'économie, de l'emploi, du travail et des solidarités, division IAE",
    )
    DGEFP = ("DGEFP", "Délégation générale à l'emploi et à la formation professionnelle")
    DIHAL = ("DIHAL", "Délégation interministérielle à l'hébergement et à l'accès au logement")
    IAE_NETWORK = ("Réseau IAE", "Réseau employeur de l'insertion par l'activité économique")
    OTHER = ("Autre", "Autre")
