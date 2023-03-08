from django.db import models


class PrescriberOrganizationKind(models.TextChoices):
    CAP_EMPLOI = "CAP_EMPLOI", "Cap emploi"
    ML = "ML", "Mission locale"
    OIL = "OIL", "Opérateur d'intermédiation locative"
    ODC = "ODC", "Organisation délégataire d'un CD"
    PENSION = "PENSION", "Pension de famille / résidence accueil"
    PE = "PE", "Pôle emploi"
    RS_FJT = "RS_FJT", "Résidence sociale / FJT - Foyer de Jeunes Travailleurs"
    PREVENTION = "PREVENTION", "Service ou club de prévention"
    DEPT = "DEPT", "Service social du conseil départemental"
    AFPA = ("AFPA", "AFPA - Agence nationale pour la formation professionnelle des adultes")
    ASE = "ASE", "ASE - Aide sociale à l'enfance"
    CAARUD = (
        "CAARUD",
        ("CAARUD - Centre d'accueil et d'accompagnement à la réduction de risques pour usagers de drogues"),
    )
    CADA = "CADA", "CADA - Centre d'accueil de demandeurs d'asile"
    CAF = "CAF", "CAF - Caisse d'allocations familiales"
    CAVA = "CAVA", "CAVA - Centre d'adaptation à la vie active"
    CCAS = ("CCAS", "CCAS - Centre communal d'action sociale ou centre intercommunal d'action sociale")
    CHRS = "CHRS", "CHRS - Centre d'hébergement et de réinsertion sociale"
    CHU = "CHU", "CHU - Centre d'hébergement d'urgence"
    CIDFF = ("CIDFF", "CIDFF - Centre d'information sur les droits des femmes et des familles")
    CPH = "CPH", "CPH - Centre provisoire d'hébergement"
    CSAPA = "CSAPA", "CSAPA - Centre de soins, d'accompagnement et de prévention en addictologie"
    E2C = "E2C", "E2C - École de la deuxième chance"
    EPIDE = "EPIDE", "EPIDE - Établissement pour l'insertion dans l'emploi"
    HUDA = "HUDA", "HUDA - Hébergement d'urgence pour demandeurs d'asile"
    MSA = "MSA", "MSA - Mutualité Sociale Agricole"
    OACAS = (
        "OACAS",
        (
            "OACAS - Structure porteuse d'un agrément national organisme "
            "d'accueil communautaire et d'activité solidaire"
        ),
    )
    PIJ_BIJ = "PIJ_BIJ", "PIJ-BIJ - Point/Bureau information jeunesse"
    PJJ = "PJJ", "PJJ - Protection judiciaire de la jeunesse"
    PLIE = "PLIE", "PLIE - Plan local pour l'insertion et l'emploi"
    SPIP = "SPIP", "SPIP - Service pénitentiaire d'insertion et de probation"
    OTHER = "Autre", "Autre"


class PrescriberAuthorizationStatus(models.TextChoices):
    NOT_SET = "NOT_SET", "Habilitation en attente de validation"
    VALIDATED = "VALIDATED", "Habilitation validée"
    REFUSED = "REFUSED", "Validation de l'habilitation refusée"
    NOT_REQUIRED = "NOT_REQUIRED", "Pas d'habilitation nécessaire"
