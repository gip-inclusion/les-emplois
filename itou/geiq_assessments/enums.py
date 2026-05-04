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


# class GEIQAction(enum.StrEnum):
#     ALLOWANCE_REQUEST_JUSTIFICATION = "allowance_request_justification"


class AllowanceJustificationReason(models.TextChoices):
    OTHER_REFERENCE_PERIOD = "other_reference_period", "Autre période de référence"
    SUPPORT_CONSIDERATION = "support_consideration", "Prise en compte de l'accompagnement"
    OTHER = "other", "Autre motif"

    @classmethod
    def get_description(cls, reason):
        details = {
            cls.OTHER_REFERENCE_PERIOD: "La période de contrat / l’accompagnement s’étend sur un autre exercice.",
            cls.SUPPORT_CONSIDERATION: (
                "L'accompagnement a débuté avant et/ou s'est poursuivi après la fin du contrat."
            ),
            cls.OTHER: "Précisez le motif dans le champ de saisie ci-dessous.",
        }
        return details.get(reason)
