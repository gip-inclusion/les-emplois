from django.db import models


class EmployeeRecordOrder(models.TextChoices):
    # HIRING_START_AT_DESC is the default value, hence its first position
    HIRING_START_AT_DESC = "-hiring_start_at", "La plus récente d'abord"
    HIRING_START_AT_ASC = "hiring_start_at", "La plus ancienne d'abord"
    NAME_ASC = "name", "Nom A - Z"
    NAME_DESC = "-name", "Nom Z - A"
