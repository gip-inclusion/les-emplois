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
    DISABLED = "DISABLED", "Désactivée"
    ARCHIVED = "ARCHIVED", "Archivée"

    @classmethod
    def displayed_choices(cls):
        """
        Hide values in forms but don't override self.choices method to keep hidden enums visible in Django admin.
        """
        empty = [(None, cls.__empty__)] if hasattr(cls, "__empty__") else []
        return empty + [(enum.value, enum.label) for enum in cls if enum is not Status.ARCHIVED]


class NotificationStatus(models.TextChoices):
    NEW = "NEW", "Nouvelle"
    SENT = "SENT", "Envoyée"
    PROCESSED = "PROCESSED", "Intégrée"
    REJECTED = "REJECTED", "En erreur"


class MovementType(models.TextChoices):
    CREATION = "C", "Création"
    UPDATE = "M", "Modification"
