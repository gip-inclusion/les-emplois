from django.urls import reverse

from itou.common_apps.address.departments import DEPARTMENT_TO_REGION, REGIONS
from itou.common_apps.notifications.base_class import BaseNotification
from itou.communications import NotificationCategory
from itou.institutions.enums import InstitutionKind
from itou.institutions.models import InstitutionMembership
from itou.utils.emails import get_email_message
from itou.utils.urls import get_absolute_url


class GEIQImplementationAssessmentSubmittedNotification(BaseNotification):
    NAME = "geiq_implementation_assessment_submitted"
    category = NotificationCategory.GEIQ_IMPLEMENTATION_ASSESSMENT

    subject_template = "geiq/email/to_institution_assessment_submitted_subject.txt"
    body_template = "geiq/email/to_institution_assessment_submitted_body.txt"

    def __init__(self, assessment):
        self.assessment = assessment

    @property
    def email(self):
        relevant_ddets_emails = InstitutionMembership.objects.filter(
            institution__department=self.assessment.company.department,
            institution__kind=InstitutionKind.DDETS_GEIQ,
            is_active=True,
        ).values_list("user__email", flat=True)
        relevant_dreets_emails = InstitutionMembership.objects.filter(
            institution__department__in=REGIONS[DEPARTMENT_TO_REGION[self.assessment.company.department]],
            institution__kind=InstitutionKind.DREETS_GEIQ,
            is_active=True,
        ).values_list("user__email", flat=True)

        to = sorted(set(relevant_ddets_emails) | set(relevant_dreets_emails))
        context = {
            "assessment": self.assessment,
            "assessment_absolute_url": get_absolute_url(
                reverse("geiq:assessment_info", kwargs={"assessment_pk": self.assessment.pk})
            ),
        }
        return get_email_message(to, context, self.subject_template, self.body_template)
