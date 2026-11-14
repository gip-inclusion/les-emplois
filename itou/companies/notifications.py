from django.urls import reverse

from itou.communications import NotificationCategory, registry as notifications_registry
from itou.communications.dispatch import EmailNotification
from itou.communications.dispatch.utils import ProfessionalNotification
from itou.companies.enums import CompanyKind
from itou.utils.urls import get_absolute_url


@notifications_registry.register
class OldJobDescriptionDeactivationNotification(EmailNotification, ProfessionalNotification):
    """Notification sent to the members of a company when an old job description is deactivated"""

    name = "Désactivation de fiche de poste"
    category = NotificationCategory.JOB_DESCRIPTION
    subject_template = "companies/email/old_job_description_deactivated_subject.txt"
    body_template = "companies/email/old_job_description_deactivated_body.md"


@notifications_registry.register
class SpontaneousJobApplicationsDeactivationNotification(EmailNotification, ProfessionalNotification):
    """Notification sent to the members of a company when spontaneous applications are deactivated"""

    name = "Désactivation des candidatures spontanées"
    category = NotificationCategory.JOB_APPLICATION
    subject_template = "companies/email/spontaneous_jobapps_deactivated_subject.txt"
    body_template = "companies/email/spontaneous_jobapps_deactivated_body.md"


@notifications_registry.register
class ProSupportReportReadNotification(ProfessionalNotification, EmailNotification):
    """Notification sent to the author of a pro support report, or to an admin if they left, once it is read"""

    name = "Bilan d’accompagnement consulté par le prescripteur"
    category = NotificationCategory.END_OF_JOURNEY
    subject_template = "companies/email/pro_support_report_read_subject.txt"
    body_template = "companies/email/pro_support_report_read_body.md"

    def is_applicable(self):
        return self.structure and self.structure.kind in CompanyKind.siae_kinds()

    def get_context(self):
        context = super().get_context()
        context["advisors_url"] = get_absolute_url(
            reverse("job_seekers_views:advisors", kwargs={"public_id": context["report"].job_seeker.public_id})
        )
        return context
