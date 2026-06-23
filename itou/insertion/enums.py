from django.db import models


class GenericReferenceItemSource(models.TextChoices):
    DATA_INCLUSION = "DATA_INCLUSION", "data·inclusion"
    DORA = "DORA", "DORA"


class GenericReferenceItemKind(models.TextChoices):
    FEE = "FEE", "Frais"
    FUNDING_LABEL = "FUNDING_LABEL", "Label de financement"
    MOBILIZATION = "MOBILIZATION", "Mode de mobilisation"
    MOBILIZATION_BENEFICIARY = "MOBILIZATION_BENEFICIARY", "Mode de mobilisation bénéficiaires"
    MOBILIZATION_PUBLIC = "MOBILIZATION_PUBLIC", "Personne mobilisatrices"
    MOBILIZATION_PROFESSIONAL = "MOBILIZATION_PROFESSIONAL", "Mode de mobilisation professionnels"
    NETWORK = "NETWORK", "Réseau porteur"
    PUBLIC = "PUBLIC", "Public"
    RECEPTION = "RECEPTION", "Mode d'accueil"
    SERVICE_KIND = "SERVICE_KIND", "Type de service"
    SOURCE = "SOURCE", "Source"
    THEMATIC = "THEMATIC", "Thématique"
