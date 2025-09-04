from itou.communications import NotificationCategory, registry as notifications_registry
from itou.communications.dispatch import (
    EmailNotification,
    EmployerNotification,
    JobSeekerNotification,
    PrescriberOrEmployerNotification,
)
from itou.job_applications.enums import RefusalReason
from itou.utils.perms.utils import _can_view_personal_information


class ProxyNotification(PrescriberOrEmployerNotification, EmailNotification):
    def get_context(self):
        context = super().get_context()
        job_application = context["job_application"]
        return context | {
            "can_view_personal_information": _can_view_personal_information(
                viewer=self.user,
                user=job_application.job_seeker,
                viewer_is_prescriber_from_authorized_org=self.user.is_prescriber_with_authorized_org_memberships,
            ),
        }


@notifications_registry.register
class JobApplicationNewForJobSeekerNotification(JobSeekerNotification, EmailNotification):
    """Notification sent to job seeker when created"""

    name = "Confirmation d’envoi de candidature"
    category = NotificationCategory.JOB_APPLICATION
    subject_template = "apply/email/new_for_job_seeker_subject.txt"
    body_template = "apply/email/new_for_job_seeker_body.txt"


@notifications_registry.register
class JobApplicationNewForProxyNotification(ProxyNotification):
    """Notification sent to proxy (prescriber or employer/orienter) when created"""

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
class JobApplicationAddedToPoolForJobSeekerNotification(JobSeekerNotification, EmailNotification):
    """Notification sent to job seeker when added to pool"""

    name = "Ajout de candidature au vivier"
    category = NotificationCategory.JOB_APPLICATION
    subject_template = "apply/email/add_to_pool_for_job_seeker_subject.txt"
    body_template = "apply/email/add_to_pool_for_job_seeker_body.txt"


@notifications_registry.register
class JobApplicationAddedToPoolForProxyNotification(ProxyNotification):
    """Notification sent to proxy (prescriber or employer/orienter) when added to pool"""

    name = "Ajout au vivier d’une candidature envoyée"
    category = NotificationCategory.JOB_APPLICATION
    subject_template = "apply/email/add_to_pool_for_proxy_subject.txt"
    body_template = "apply/email/add_to_pool_for_proxy_body.txt"


@notifications_registry.register
class JobApplicationPostponedForJobSeekerNotification(JobSeekerNotification, EmailNotification):
    """Notification sent to job seeker when postponed"""

    name = "Mise en attente de candidature"
    category = NotificationCategory.JOB_APPLICATION
    subject_template = "apply/email/postpone_for_job_seeker_subject.txt"
    body_template = "apply/email/postpone_for_job_seeker_body.txt"


@notifications_registry.register
class JobApplicationPostponedForProxyNotification(ProxyNotification):
    """Notification sent to proxy (prescriber or employer/orienter) when postponed"""

    name = "Mise en attente d’une candidature envoyée"
    category = NotificationCategory.JOB_APPLICATION
    subject_template = "apply/email/postpone_for_proxy_subject.txt"
    body_template = "apply/email/postpone_for_proxy_body.txt"


@notifications_registry.register
class JobApplicationAcceptedForJobSeekerNotification(JobSeekerNotification, EmailNotification):
    """Notification sent to job seeker when accepted"""

    name = "Confirmation d’acceptation de candidature"
    category = NotificationCategory.JOB_APPLICATION
    subject_template = "apply/email/accept_for_job_seeker_subject.txt"
    body_template = "apply/email/accept_for_job_seeker_body.txt"


@notifications_registry.register
class JobApplicationAcceptedForProxyNotification(ProxyNotification):
    """Notification sent to proxy (prescriber or employer/orienter) when accepted"""

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


@notifications_registry.register
class JobApplicationRefusedForProxyNotification(ProxyNotification):
    """Notification sent to proxy (prescriber or employer/orienter) when refused"""

    name = "Refus de candidature"
    category = NotificationCategory.JOB_APPLICATION
    subject_template = "apply/email/refuse_subject.txt"
    body_template = "apply/email/refuse_body_for_proxy.txt"

    def is_applicable(self):
        if job_application := self.context.get("job_application"):
            return super().is_applicable() and job_application.refusal_reason != RefusalReason.AUTO
        return super().is_applicable()


@notifications_registry.register
class JobApplicationTransferredForJobSeekerNotification(JobSeekerNotification, EmailNotification):
    """Notification sent to job seeker when transferred"""

    name = "Transfert de candidature"
    category = NotificationCategory.JOB_APPLICATION
    subject_template = "apply/email/transfer_job_seeker_subject.txt"
    body_template = "apply/email/transfer_job_seeker_body.txt"


@notifications_registry.register
class JobApplicationTransferredForProxyNotification(ProxyNotification):
    """Notification sent to proxy (prescriber or employer/orienter) when transferred"""

    name = "Transfert d'une candidature envoyée"
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
class JobApplicationCanceledNotification(ProxyNotification):
    name = "Embauche annulée"
    category = NotificationCategory.JOB_APPLICATION
    subject_template = "apply/email/cancel_subject.txt"
    body_template = "apply/email/cancel_body.txt"
