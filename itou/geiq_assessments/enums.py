import enum

from django.db import models


class AssessmentContractDetailsTab(models.TextChoices):
    EMPLOYEE = "employee", "Informations salarié"
    CONTRACT = "contract", "Contrat"
    SUPPORT_AND_TRAINING = "support-and-training", "Accompagnement et formation"
    EXIT = "exit", "Sortie"
    ALLOWANCE_REQUEST_JUSTIFICATION = "request-justification", "Justification"
    ALLOWANCE_REFUSAL_JUSTIFICATION = "refusal-justification", "Motif de refus"

    @classmethod
    def get_common_tabs(cls):
        return [cls.EMPLOYEE, cls.CONTRACT, cls.SUPPORT_AND_TRAINING, cls.EXIT]

    @classmethod
    def get_employer_tabs(cls):
        return cls.get_common_tabs() + [cls.ALLOWANCE_REQUEST_JUSTIFICATION]

    @classmethod
    def get_institution_tabs(cls):
        return cls.get_common_tabs() + [cls.ALLOWANCE_REFUSAL_JUSTIFICATION]


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


class AllowanceRefusalReason(models.TextChoices):
    UNCONFIRMED_ELIGIBILITY = "unconfirmed_eligibility", "Éligibilité du salarié non confirmée"
    ALLOWANCE_ALREADY_GRANTED = "allowance_already_granted", "Aide déjà attribuée"
    OTHER = "other", "Autre motif"

    @classmethod
    def get_description(cls, reason):
        details = {
            cls.UNCONFIRMED_ELIGIBILITY: "Le GEIQ n’a pas pu fournir les justificatifs nécessaires à "
            "la confirmation de l’éligibilité du salarié.",
            cls.ALLOWANCE_ALREADY_GRANTED: "Une aide a déjà été attribuée pour ce salarié.",
            cls.OTHER: "Précisez le motif dans le champ de saisie ci-dessous.",
        }
        return details.get(reason)


class EmployerAction(enum.StrEnum):
    REQUEST_ALLOWANCE = "request_allowance"
    UNREQUEST_ALLOWANCE = "unrequest_allowance"

    # Make the Enum work in Django's templates
    # See :
    # - https://docs.djangoproject.com/en/dev/ref/templates/api/#variables-and-lookups
    # - https://github.com/django/django/pull/12304
    do_not_call_in_templates = enum.nonmember(True)


class InstitutionAction(enum.StrEnum):
    REVIEW = "review"
    ASK_FOR_INSTITUTION_FIX = "ask_for_institution_fix"
    ASK_FOR_GEIQ_FIX = "ask_for_geiq_fix"
    REFUSE_ALLOWANCE = "refuse_allowance"
    GRANT_ALLOWANCE = "grant_allowance"
    ALLOWANCE_REFUSAL_JUSTIFICATION = "allowance_refusal_justification"

    # Make the Enum work in Django's templates
    # See :
    # - https://docs.djangoproject.com/en/dev/ref/templates/api/#variables-and-lookups
    # - https://github.com/django/django/pull/12304
    do_not_call_in_templates = enum.nonmember(True)


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
