from itou.communications import NotificationCategory, registry as notifications_registry
from itou.communications.dispatch import EmailNotification
from itou.utils.urls import get_absolute_url


@notifications_registry.register
class AssessmentSubmittedForLaborInspectorNotification(EmailNotification):
    """Notification sent to the members of the DDETS/DREETS conventionned with the assessment on submission"""

    name = "Soumission de bilan d’exécution"
    category = NotificationCategory.GEIQ_IMPLEMENTATION_ASSESSMENT
    can_be_disabled = False
    subject_template = "geiq_assessments/email/assessment_submission_subject.txt"
    body_template = "geiq_assessments/email/assessment_submission_body.txt"

    def get_context(self):
        context = super().get_context()
        context["base_url"] = get_absolute_url()
        return context


@notifications_registry.register
class AssessmentReviewedForDREETSLaborInspectorNotification(EmailNotification):
    """Notification sent to the members of the DREETS linked with the assessment on DDETS review"""

    name = "Validation de bilan d’exécution"
    category = NotificationCategory.GEIQ_IMPLEMENTATION_ASSESSMENT
    can_be_disabled = False
    subject_template = "geiq_assessments/email/assessment_review_for_dreets_subject.txt"
    body_template = "geiq_assessments/email/assessment_review_for_dreets_body.txt"

    def get_context(self):
        context = super().get_context()
        context["base_url"] = get_absolute_url()
        return context


@notifications_registry.register
class AssessmentReviewedForGeiqNotification(EmailNotification):
    """Notification sent to the members of the GEIQ linked to the assessment on final review"""

    name = "Validation de bilan d’exécution"
    category = NotificationCategory.GEIQ_IMPLEMENTATION_ASSESSMENT
    can_be_disabled = False
    subject_template = "geiq_assessments/email/assessment_review_for_geiq_subject.txt"
    body_template = "geiq_assessments/email/assessment_review_for_geiq_body.txt"

    def get_context(self):
        context = super().get_context()
        assessment = context["assessment"]
        context["abs_balance_amount"] = abs(assessment.granted_amount - assessment.advance_amount)
        return context
