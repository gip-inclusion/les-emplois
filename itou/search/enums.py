from django.db import models


class SearchType(models.TextChoices):
    EMPLOYERS = "employers", "employeurs"
    PRESCRIBERS = "prescribers", "accompagnateurs"
    SERVICES = "services", "services"
