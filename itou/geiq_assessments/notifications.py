from itou.communications import NotificationCategory, registry as notifications_registry
from itou.communications.dispatch import EmailNotification
from itou.geiq_assessments.models import (
    AssessmentInstitutionLink,
)
from itou.institutions.models import InstitutionMembership
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

    def build(self):
        email_message = super().build()
        assessment = self.context["assessment"]
        cc_users = {
            membership.user
            for membership in InstitutionMembership.objects.active()
            .filter(
                institution__in=AssessmentInstitutionLink.objects.filter(
                    assessment=assessment, with_convention=True
                ).values_list("institution", flat=True),
            )
            .select_related("user")
        }
        # TODO: handle case where more than 50 CC users are found (cf Mailjet limit)
        email_message.cc = sorted(cc_user.email for cc_user in cc_users)
        return email_message
