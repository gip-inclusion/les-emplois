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
    INSTITUTION_FIX = "institution_fix"

    @classmethod
    def with_timestamp_match(cls):
        return {cls.SUBMIT, cls.REVIEW, cls.FINAL_REVIEW}
