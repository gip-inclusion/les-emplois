from django.db import models


class Status(models.TextChoices):
    """
    Status of the employee record

    Self-explanatory on the meaning, however:
    - an employee record can be modified until it is in the PROCESSED state
    - after that, the object is "archived" and can't be used for further interaction
    """

    NEW = "NEW", "Nouvelle"
    READY = "READY", "Complétée"
    SENT = "SENT", "Envoyée"
    REJECTED = "REJECTED", "En erreur"
    PROCESSED = "PROCESSED", "Intégrée"
    ARCHIVED = "ARCHIVED", "Archivée"


class NotificationStatus(models.TextChoices):
    NEW = "NEW", "Nouvelle"
    SENT = "SENT", "Envoyée"
    PROCESSED = "PROCESSED", "Intégrée"
    REJECTED = "REJECTED", "En erreur"


class NotificationType(models.TextChoices):
    """
    Add a new type for each new employee record update notification.
    """

    APPROVAL = "APPROVAL", "Modification du PASS IAE"
    JOB_SEEKER = "JOB_SEEKER", "Modification de l'employé"


class MovementType(models.TextChoices):
    CREATION = "C", "Création"
    UPDATE = "M", "Modification"
