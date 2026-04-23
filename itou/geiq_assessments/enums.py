import enum

from django.db import models


class AssessmentState(models.TextChoices):
    NEW = "new", "À compléter"
    SUBMITTED = "submitted", "Envoyé"
    REVIEWED = "reviewed", "Contrôlé"
    FINAL_REVIEWED = "final_reviewed", "Contrôlé (DREETS)"


class AssessmentTransition(enum.StrEnum):
    SUBMIT = "submit"
    REVIEW = "review"
    FINAL_REVIEW = "final_review"
    ASK_FOR_INSTITUTION_FIX = "ask_for_institution_fix"
    ASK_FOR_GEIQ_FIX = "ask_for_geiq_fix"

    @classmethod
    def with_timestamp_match(cls):
        return {cls.SUBMIT, cls.REVIEW, cls.FINAL_REVIEW}


class InstitutionAction(enum.StrEnum):
    REVIEW = "review"
    ASK_FOR_INSTITUTION_FIX = "ask_for_institution_fix"
    ASK_FOR_GEIQ_FIX = "ask_for_geiq_fix"

    # Make the Enum work in Django's templates
    # See :
    # - https://docs.djangoproject.com/en/dev/ref/templates/api/#variables-and-lookups
    # - https://github.com/django/django/pull/12304
    do_not_call_in_templates = enum.nonmember(True)
