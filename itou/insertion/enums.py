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


class MobilizationEventKind(models.TextChoices):
    SERVICE_ORIENTATION = "service_orientation", "Orientation vers un service"
    SERVICE_EXT_LINK = "service_ext_link", "Orientation via un lien externe ou clic sur un lien de démarche à réaliser"
    SERVICE_CONTACT = "service_contact", "Affichage des informations de contact du service"
    STRUCTURE_CONTACT = "structure_contact", "Affichage des informations de contact de la structure"


class BeneficiaryContactPreference(models.TextChoices):
    PHONE = "TELEPHONE", "Téléphone"
    EMAIL = "EMAIL", "E-mail"
    REFERENT = "REFERENT", "Via le conseiller référent"
    OTHER = "AUTRE", "Autre"


class OrientationStatus(models.TextChoices):
    MODERATION_PENDING = "MODÉRATION_EN_COURS", "En cours de modération"
    MODERATION_REJECTED = "MODÉRATION_REJETÉE", "Rejetée par la modération"
    PENDING = "OUVERTE", "Ouverte / En cours de traitement"
    ACCEPTED = "VALIDÉE", "Validée"
    REJECTED = "REFUSÉE", "Refusée"
    EXPIRED = "EXPIRÉE", "Expirée"
