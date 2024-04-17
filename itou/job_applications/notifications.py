from itou.common_apps.notifications.base_class import BaseNotification
from itou.communications import NotificationCategory, registry as notifications_registry
from itou.communications.dispatch import (
    EmailNotification,
    EmployerNotification,
    JobSeekerNotification,
    PrescriberNotification,
    PrescriberOrEmployerNotification,
)
from itou.job_applications.utils import show_afpa_ad
from itou.utils.emails import get_email_message


class NewSpontaneousJobAppEmployersNotification(BaseNotification):
    NAME = "new_spontaneous_job_application_employers_email"

    def __init__(self, job_application):
        self.job_application = job_application
        active_memberships = job_application.to_company.companymembership_set.active()
        super().__init__(recipients_qs=active_memberships)

    @property
    def email(self):
        to = self.recipients_emails
        context = {"job_application": self.job_application}
        subject = "apply/email/new_for_employer_subject.txt"
        body = "apply/email/new_for_employer_body.txt"
        return get_email_message(to, context, subject, body)

    @property
    def recipients_emails(self):
        return self.get_recipients().values_list("user__email", flat=True)


@notifications_registry.register
class JobApplicationNewForJobSeekerNotification(JobSeekerNotification, EmailNotification):
    """Notification sent to job seeker when created"""

    name = "Confirmation d’envoi de candidature"
    category = NotificationCategory.JOB_APPLICATION
    subject_template = "apply/email/new_for_job_seeker_subject.txt"
    body_template = "apply/email/new_for_job_seeker_body.txt"


@notifications_registry.register
class JobApplicationNewForPrescriberNotification(PrescriberNotification, EmailNotification):
    """Notification sent to prescriber when created"""

    name = "Confirmation d’envoi de candidature"
    category = NotificationCategory.JOB_APPLICATION
    subject_template = "apply/email/new_for_prescriber_subject.txt"
    body_template = "apply/email/new_for_prescriber_body.txt"


@notifications_registry.register
class JobApplicationNewForEmployerNotification(EmployerNotification, EmailNotification):
    """Notification sent to new employers when created"""

    name = "Nouvelle candidature"
    category = NotificationCategory.JOB_APPLICATION
    subject_template = "apply/email/new_for_employer_subject.txt"
    body_template = "apply/email/new_for_employer_body.txt"


@notifications_registry.register
class JobApplicationAcceptedForJobSeekerNotification(JobSeekerNotification, EmailNotification):
    """Notification sent to job seeker when accepted"""

    name = "Confirmation d’acceptation de candidature"
    category = NotificationCategory.JOB_APPLICATION
    subject_template = "apply/email/accept_for_job_seeker_subject.txt"
    body_template = "apply/email/accept_for_job_seeker_body.txt"


@notifications_registry.register
class JobApplicationAcceptedForPrescriberNotification(PrescriberNotification, EmailNotification):
    """Notification sent to prescriber when accepted"""

    name = "Confirmation d’acceptation de candidature"
    category = NotificationCategory.JOB_APPLICATION
    subject_template = "apply/email/accept_for_proxy_subject.txt"
    body_template = "apply/email/accept_for_proxy_body.txt"

    def get_context(self):
        context = super().get_context()
        job_application = context["job_application"]
        if job_application.sender_prescriber_organization:
            # Include the survey link for all prescribers's organizations.
            context["prescriber_survey_link"] = job_application.sender_prescriber_organization.accept_survey_url
        else:
            context["prescriber_survey_link"] = None
        return context


@notifications_registry.register
class JobApplicationRefusedForJobSeekerNotification(JobSeekerNotification, EmailNotification):
    """Notification sent to job seeker when transferred"""

    name = "Refus de candidature"
    category = NotificationCategory.JOB_APPLICATION
    subject_template = "apply/email/refuse_subject.txt"
    body_template = "apply/email/refuse_body_for_job_seeker.txt"

    def get_context(self):
        context = super().get_context()
        context["show_afpa_ad"] = show_afpa_ad(self.user)
        return context


@notifications_registry.register
class JobApplicationRefusedForPrescriberNotification(PrescriberNotification, EmailNotification):
    """Notification sent to prescriber when refused"""

    name = "Refus de candidature"
    category = NotificationCategory.JOB_APPLICATION
    subject_template = "apply/email/refuse_subject.txt"
    body_template = "apply/email/refuse_body_for_proxy.txt"


@notifications_registry.register
class JobApplicationTransferredForJobSeekerNotification(JobSeekerNotification, EmailNotification):
    """Notification sent to job seeker when transferred"""

    name = "Transfert de candidature"
    category = NotificationCategory.JOB_APPLICATION
    subject_template = "apply/email/transfer_job_seeker_subject.txt"
    body_template = "apply/email/transfer_job_seeker_body.txt"


@notifications_registry.register
class JobApplicationTransferredForPrescriberNotification(PrescriberNotification, EmailNotification):
    """Notification sent to prescriber when transferred"""

    name = "Transfert de candidature"
    category = NotificationCategory.JOB_APPLICATION
    subject_template = "apply/email/transfer_prescriber_subject.txt"
    body_template = "apply/email/transfer_prescriber_body.txt"


@notifications_registry.register
class JobApplicationTransferredForEmployerNotification(EmployerNotification, EmailNotification):
    """Notification sent to original employer when transferred"""

    name = "Transfert de candidature"
    category = NotificationCategory.JOB_APPLICATION
    subject_template = "apply/email/transfer_source_employer_subject.txt"
    body_template = "apply/email/transfer_source_employer_body.txt"


@notifications_registry.register
class JobApplicationCanceledNotification(PrescriberOrEmployerNotification, EmailNotification):
    name = "Embauche annulée"
    category = NotificationCategory.JOB_APPLICATION
    subject_template = "apply/email/cancel_subject.txt"
    body_template = "apply/email/cancel_body.txt"
