from django.db import models


class InstitutionKind(models.TextChoices):
    DDETS = ("DDETS", "Direction départementale de l'emploi, du travail et des solidarités")
    DREETS = ("DREETS", "Direction régionale de l'économie, de l'emploi, du travail et des solidarités")
    DGEFP = ("DGEFP", "Délégation générale à l'emploi et à la formation professionnelle")
    DIHAL = ("DIHAL", "Délégation interministérielle à l'hébergement et à l'accès au logement")
    IAE_NETWORK = ("Réseau IAE", "Réseau IAE (Coorace, Emmaüs...)")
    OTHER = ("Autre", "Autre")
