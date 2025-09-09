from itou.communications import NotificationCategory, registry as notifications_registry
from itou.communications.dispatch import EmailNotification
from itou.communications.dispatch.utils import EmployerNotification


@notifications_registry.register
class OldJobDescriptionDeactivationNotification(EmailNotification, EmployerNotification):
    """Notification sent to the members of a company when an old job description is deactivated"""

    name = "Désactivation de fiche de poste"
    category = NotificationCategory.JOB_DESCRIPTION
    subject_template = "companies/email/old_job_description_deactivated_subject.txt"
    body_template = "companies/email/old_job_description_deactivated_body.txt"
