from django.db import models


class Channel(models.TextChoices):
    FROM_COWORKER = "from_coworker"
    FROM_NIR = "from_nir"
    FROM_NAME_EMAIL = "from_name_email"
