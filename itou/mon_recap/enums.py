from django.db import models


class NotebookOrderKind(models.IntegerChoices):
    DISCOVERY = 2, "2 - Commande decouverte"
    HIGH_PRIORITY = 3, "3 - Commande dpt prio"
    QUOTATION_REQUEST = 4, "4 - Demande de devis"
    DIAG_KO = 5, "5 - Diag ko"


class NotebookOrderState(models.TextChoices):
    # FIXME: mostly placeholder, to validate
    NEW = "NEW", "Nouvelle commande"
    CANCELLED = "CANCELLED", "Commande annulée"
    PROCESSED = "PROCESSED", "Commande expédiée"
    RECEIVED = "RECEIVED", "Commande reçue"


class OrganizationKind(models.TextChoices):
    FORMATION = "FORMATION", "Organisme de formation"
    NON_PROFIT = "NON_PROFIT", "Association"
    SIAE = "SIAE", "SIAE"
    PUBLIC_SERVICE = "PUBLIC_SERVICE", "Service public"
    CHRS = "CHRS", "CHRS/Accueil de jour"
    OTHER = "OTHER", "Autre"


class OrganizationNetwork(models.TextChoices):
    ADOMA = "ADOMA", "Adoma"
    APPRENTIS_AUTEUIL = "APPRENTIS_AUTEUIL", "Apprentis d'auteuil"
    ARMEE_DU_SALUT = "ARMEE_DU_SALUT", "Armée du salut"
    ATD_QUART_MONDE = "ATD_QUART_MONDE", "ATD Quart Monde"
    CAP_EMPLOI = "CAP_EMPLOI", "Cap Emploi"
    CCAS = "CCAS", "CCAS"
    CCFD = "CCFD", "CCFD"
    CIDFF = "CIDFF", "CIDFF"
    COALLIA = "COALLIA", "Coallia"
    CPAM = "CPAM", "CPAM"
    CD = "CD", "Conseil Départemental"
    EPIDE = "EPIDE", "Epide"
    FT = "FT", "France Travail"
    ML = "ML", "Mission locale"
    PIMMS = "PIMMS", "PIMMS"
    PLIE = "PLIE", "PLIE"
    RESTOS_DU_COEUR = "RESTOS_DU_COEUR", "Resto du coeur"
    SINGA = "SINGA", "Singa"
    SNC = "SNC", "SNC"
    SYNERGIE_FAMILY = "SYNERGIE_FAMILY", "Synergie Family"
    OTHER = "OTHER", "Autre"


class RequesterKind(models.TextChoices):
    COUNSELOR = "COUNSELOR", "Accompagnateur : en lien direct avec les usagers"
    MANAGER = "MANAGER", "Responsable/directeur/coordinateur...: en lien avec les accompagnateurs"


class DiscoverySource(models.TextChoices):
    COUNSELOR = "COUNSELOR", "Via un autre professionnel de l'accompagnement"
    BENEFICIARY = "BENEFICIARY", "Via une personne que j'accompagne"
    PDI_PRODUCT = (
        "PDI_PRODUCT",
        "Via un autre service de la Plateforme de l'inclusion (Dora, les Emplois, Immersion facilitée ...)",
    )
    EMAIL = "EMAIL", "Via un mail de Mon Récap"
    WEBINAR = "WEBINAR", "Via un webinaire de présentation de Mon Récap"
    MEETING = "MEETING", "Via une rencontre terrain avec l'équipe Mon Récap"
    LINKEDIN = "LINKEDIN", "Via LinkedIn"
    GOOGLE = "GOOGLE", "Recherche générique sur Google"
    OTHER = "OTHER", "Autre"


class PublicObstacles(models.TextChoices):
    MOBILITY = "MOBILITY", "Mobilité"
    DIGITAL = "DIGITAL", "Numérique"
    HEALTH = "HEALTH", "Santé/handicap"
    HOUSING = "HOUSING", "Logement"
    FAMILY = "FAMILY", "Famille/garde d'enfants"
    LANGUAGE = "LANGUAGE", "Langue"
    OTHER = "OTHER", "Autre"
