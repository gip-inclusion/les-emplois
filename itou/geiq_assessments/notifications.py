from itou.communications import NotificationCategory, registry as notifications_registry
from itou.communications.dispatch import EmailNotification


@notifications_registry.register
class AssessmentSubmittedForLaborInspectorNotification(EmailNotification):
    """Notification sent to the members of the DDETS/DREETS linked to the assessment with a convention"""

    name = "Soumission de bilan d’exécution"
    category = NotificationCategory.GEIQ_IMPLEMENTATION_ASSESSMENT
    can_be_disabled = False
    subject_template = "geiq_assessments/email/assessment_submission_subject.txt"
    body_template = "geiq_assessments/email/assessment_submission_body.txt"


@notifications_registry.register
class AssessmentReviewedForDREETSLaborInspectorNotification(EmailNotification):
    """Notification sent to the members of the DDETS/DREETS linked to the assessment with a convention"""

    name = "Validation de bilan d’exécution"
    category = NotificationCategory.GEIQ_IMPLEMENTATION_ASSESSMENT
    can_be_disabled = False
    subject_template = "geiq_assessments/email/assessment_review_for_dreets_subject.txt"
    body_template = "geiq_assessments/email/assessment_review_for_dreets_body.txt"


@notifications_registry.register
class AssessmentReviewedForGeiqNotification(EmailNotification):
    """Notification sent to the members of the DDETS/DREETS linked to the assessment with a convention"""

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
