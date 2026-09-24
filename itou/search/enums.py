from django.db import models


class SearchType(models.TextChoices):
    EMPLOYERS = "employers", "employeurs"
    PRESCRIBERS = "prescribers", "accompagnateur"
    SERVICES = "services", "services"
