from django.urls import reverse

from itou.common_apps.address.departments import DEPARTMENT_TO_REGION, REGIONS
from itou.institutions.enums import InstitutionKind
from itou.institutions.models import InstitutionMembership
from itou.utils.emails import get_email_message
from itou.utils.urls import get_absolute_url


class GIEQImplementationAssessmentFactory:
    def __init__(self, assessment):
        self.assessment = assessment

    def submitted(self):
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
        subject = "geiq/email/to_institution_assessment_submitted_subject.txt"
        body = "geiq/email/to_institution_assessment_submitted_body.txt"
        return get_email_message(to, context, subject, body)
