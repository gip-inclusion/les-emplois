import enum

from django.db import models


class EmployeeRecordOrder(models.TextChoices):
    # HIRING_START_AT_DESC is the default value, hence its first position
    HIRING_START_AT_DESC = "-hiring_start_at", "La plus récente d'abord"
    HIRING_START_AT_ASC = "hiring_start_at", "La plus ancienne d'abord"
    NAME_ASC = "name", "Nom A - Z"
    NAME_DESC = "-name", "Nom Z - A"


class MissingEmployeeCase(enum.StrEnum):
    NO_HIRING = "no_hiring"
    NO_APPROVAL = "no_approval"
    EXISTING_EMPLOYEE_RECORD_SAME_COMPANY = "existing_employee_record_same_company"
    EXISTING_EMPLOYEE_RECORD_OTHER_COMPANY = "existing_employee_record_other_company"
    NO_EMPLOYEE_RECORD = "no_employee_record"

    # Make the Enum work in Django's templates
    # See :
    # - https://docs.djangoproject.com/en/dev/ref/templates/api/#variables-and-lookups
    # - https://github.com/django/django/pull/12304
    do_not_call_in_templates = enum.nonmember(True)
