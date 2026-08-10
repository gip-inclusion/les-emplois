import enum

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
    PHONE = "TELEPHONE", "téléphone"
    EMAIL = "EMAIL", "e-mail"
    REFERENT = "REFERENT", "via le conseiller référent"
    OTHER = "AUTRE", "autre"


class OrientationStatus(models.TextChoices):
    PENDING = "OUVERTE", "En cours de traitement"
    PROCESSING = "ÉTUDE", "À l’étude"
    ACCEPTED = "VALIDÉE", "Validée"
    EXPIRED = "EXPIRÉE", "Expirée"
    REFUSED = "REFUSÉE", "Déclinée"


class OrientationTransition(enum.StrEnum):
    PROCESS = "process"
    ACCEPT = "accept"
    REFUSE = "refuse"
    EXPIRE = "expire"


class OrientationRefusalReason(models.TextChoices):
    NOT_REACHABLE = "not_reachable", "Bénéficiaire non joignable"
    DID_NOT_COME_TO_INTERVIEW = "did_not_come_to_interview", "Bénéficiaire ne s’étant pas présenté à l’entretien"
    HIRED_ELSEWHERE = "hired_elsewhere", "Bénéficiaire indisponible : en emploi"
    TRAINING = "training", "Bénéficiaire indisponible : en formation"
    NOT_ELIGIBLE = "not_eligible", "Bénéficiaire non éligible (ne répond pas aux pré-requis)"
    NOT_MOBILE = "not_mobile", "Bénéficiaire non mobile"
    NOT_INTERESTED = "not_interested", "Bénéficiaire non intéressé"
    INCOMPATIBLE = "incompatible", "Un ou plusieurs freins périphériques empêchent le bénéficiaire de poursuivre"
    SESSION_FULL = "session_full", "Session complète"
    DUPLICATE = "duplicate", "Orientation en doublon"
    OTHER = "other", "Autre (détails dans le message ci-dessous)"
