from django.urls import reverse

from itou.communications import NotificationCategory, registry as notifications_registry
from itou.communications.dispatch import EmailNotification, EmployerNotification, JobSeekerNotification
from itou.communications.dispatch.utils import PrescriberNotification
from itou.companies.enums import CompanyKind
from itou.utils.urls import get_absolute_url


@notifications_registry.register
class ProlongationRequestCreatedForPrescriberNotification(PrescriberNotification, EmailNotification):
    """Notification sent to the authorized prescriber when a prolongation request is created"""

    name = "Nouvelle demande de prolongation"
    category = NotificationCategory.IAE_PASS
    can_be_disabled = False
    subject_template = "approvals/email/prolongation_request/created_subject.txt"
    body_template = "approvals/email/prolongation_request/created_body.txt"

    def get_context(self):
        context = super().get_context()
        context["report_file_url"] = get_absolute_url(
            reverse(
                "approvals:prolongation_request_report_file",
                kwargs={"prolongation_request_id": context["prolongation_request"].pk},
            )
        )
        return context


@notifications_registry.register
class ProlongationRequestCreatedReminderForPrescriberNotification(PrescriberNotification, EmailNotification):
    """Notification sent to the other members of the prescriber organization"""

    name = "Rappel de demande de prolongation"
    category = NotificationCategory.IAE_PASS
    can_be_disabled = False
    subject_template = "approvals/email/prolongation_request/created_reminder_subject.txt"
    body_template = "approvals/email/prolongation_request/created_reminder_body.txt"

    def get_context(self):
        context = super().get_context()
        context["report_file_url"] = get_absolute_url(
            reverse(
                "approvals:prolongation_request_report_file",
                kwargs={"prolongation_request_id": context["prolongation_request"].pk},
            )
        )
        return context


@notifications_registry.register
class ProlongationRequestDeniedForEmployerNotification(EmployerNotification, EmailNotification):
    """Notification sent to the employer when the prolongation request is denied"""

    name = "Demande de prolongation refusée"
    category = NotificationCategory.IAE_PASS
    subject_template = "approvals/email/prolongation_request/denied/employer_subject.txt"
    body_template = "approvals/email/prolongation_request/denied/employer_body.txt"

    def is_applicable(self):
        return self.structure and self.structure.kind in CompanyKind.siae_kinds()


@notifications_registry.register
class ProlongationRequestDeniedForJobSeekerNotification(JobSeekerNotification, EmailNotification):
    """Notification sent to the jobseeker when the prolongation request is denied"""

    name = "Demande de prolongation refusée"
    category = NotificationCategory.IAE_PASS
    subject_template = "approvals/email/prolongation_request/denied/jobseeker_subject.txt"
    body_template = "approvals/email/prolongation_request/denied/jobseeker_body.txt"


@notifications_registry.register
class PassAcceptedEmployerNotification(EmployerNotification, EmailNotification):
    name = "PASS IAE accepté"
    category = NotificationCategory.IAE_PASS
    subject_template = "approvals/email/deliver_subject.txt"
    body_template = "approvals/email/deliver_body.txt"

    def get_context(self):
        context = super().get_context()
        context.setdefault("siae_survey_link", context["job_application"].to_company.accept_survey_url)
        return context

    def validate_context(self):
        if not self.context["job_application"].approval:
            raise RuntimeError("No approval found for this job application.")
        return self.context

    def is_applicable(self):
        return self.structure and self.structure.kind in CompanyKind.siae_kinds()


@notifications_registry.register
class ProlongationRequestGrantedForEmployerNotification(EmployerNotification, EmailNotification):
    name = "Demande de prolongation acceptée"
    category = NotificationCategory.IAE_PASS
    subject_template = "approvals/email/prolongation_request/granted/employer_subject.txt"
    body_template = "approvals/email/prolongation_request/granted/employer_body.txt"

    def is_applicable(self):
        return self.structure and self.structure.kind in CompanyKind.siae_kinds()


@notifications_registry.register
class ProlongationRequestGrantedForJobSeekerNotification(JobSeekerNotification, EmailNotification):
    name = "Demande de prolongation acceptée"
    category = NotificationCategory.IAE_PASS
    subject_template = "approvals/email/prolongation_request/granted/jobseeker_subject.txt"
    body_template = "approvals/email/prolongation_request/granted/jobseeker_body.txt"
