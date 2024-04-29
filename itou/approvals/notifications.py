from django.db.models import F
from django.urls import reverse

from itou.common_apps.notifications.base_class import BaseNotification
from itou.communications import NotificationCategory, registry as notifications_registry
from itou.communications.dispatch import EmailNotification, EmployerNotification, JobSeekerNotification
from itou.companies.enums import SIAE_WITH_CONVENTION_KINDS
from itou.job_applications.utils import show_afpa_ad
from itou.prescribers.models import PrescriberMembership
from itou.utils.emails import get_email_message
from itou.utils.urls import get_absolute_url


class ProlongationRequestCreated(BaseNotification):
    """Notification sent to the authorized prescriber when a prolongation request is created"""

    NAME = "prolongation_request_created"

    def __init__(self, prolongation_request):
        self.prolongation_request = prolongation_request

    @property
    def email(self):
        to = [self.prolongation_request.validated_by.email]
        context = {
            "prolongation_request": self.prolongation_request,
            "report_file_url": get_absolute_url(
                reverse(
                    "approvals:prolongation_request_report_file",
                    kwargs={"prolongation_request_id": self.prolongation_request.pk},
                )
            ),
        }
        subject = "approvals/email/prolongation_request/created_subject.txt"
        body = "approvals/email/prolongation_request/created_body.txt"
        return get_email_message(to, context, subject, body)


class ProlongationRequestCreatedReminder(BaseNotification):
    """Notification sent to the other members of the prescriber organization"""

    def __init__(self, prolongation_request):
        self.prolongation_request = prolongation_request

    @property
    def email(self):
        to = [self.prolongation_request.validated_by.email]
        cc = (
            PrescriberMembership.objects.active()
            .filter(organization=self.prolongation_request.prescriber_organization)
            .exclude(user=self.prolongation_request.validated_by)
            # Limit to the last 10 active colleagues, admins take precedence over regular members.
            # It should cover the ones dedicated to the IAE and some more.
            .order_by("-is_admin", F("user__last_login").desc(nulls_last=True), "-joined_at", "-pk")[:10]
            .values_list("user__email", flat=True)
        )
        context = {
            "prolongation_request": self.prolongation_request,
            "report_file_url": get_absolute_url(
                reverse(
                    "approvals:prolongation_request_report_file",
                    kwargs={"prolongation_request_id": self.prolongation_request.pk},
                )
            ),
        }
        subject = "approvals/email/prolongation_request/created_reminder_subject.txt"
        body = "approvals/email/prolongation_request/created_reminder_body.txt"
        return get_email_message(to, context, subject, body, cc=cc)


class ProlongationRequestDeniedEmployer(BaseNotification):
    """Notification sent to the employer when the prolongation request is denied"""

    NAME = "prolongation_request_denied_employer"

    def __init__(self, prolongation_request):
        self.prolongation_request = prolongation_request

    @property
    def email(self):
        to = [self.prolongation_request.declared_by.email]
        context = {"prolongation_request": self.prolongation_request}
        subject = "approvals/email/prolongation_request/denied/employer_subject.txt"
        body = "approvals/email/prolongation_request/denied/employer_body.txt"
        return get_email_message(to, context, subject, body)


class ProlongationRequestDeniedJobSeeker(BaseNotification):
    """Notification sent to the jobseeker when the prolongation request is denied"""

    NAME = "prolongation_request_denied_jobseeker"

    def __init__(self, prolongation_request):
        self.prolongation_request = prolongation_request

    @property
    def email(self):
        user = self.prolongation_request.approval.user
        to = [user.email]
        context = {
            "prolongation_request": self.prolongation_request,
            "show_afpa_ad": show_afpa_ad(user),
        }
        subject = "approvals/email/prolongation_request/denied/jobseeker_subject.txt"
        body = "approvals/email/prolongation_request/denied/jobseeker_body.txt"
        return get_email_message(to, context, subject, body)


@notifications_registry.register
class PassAcceptedEmployerNotification(EmployerNotification, EmailNotification):
    name = "PASS IAE accepté"
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
        return self.structure and self.structure.kind in SIAE_WITH_CONVENTION_KINDS


@notifications_registry.register
class ProlongationRequestGrantedForEmployerNotification(EmployerNotification, EmailNotification):
    name = "Demande de prolongation acceptée"
    category = NotificationCategory.IAE_PASS
    subject_template = "approvals/email/prolongation_request/granted/employer_subject.txt"
    body_template = "approvals/email/prolongation_request/granted/employer_body.txt"

    def is_applicable(self):
        return self.structure and self.structure.kind in SIAE_WITH_CONVENTION_KINDS


@notifications_registry.register
class ProlongationRequestGrantedForJobSeekerNotification(JobSeekerNotification, EmailNotification):
    name = "Demande de prolongation acceptée"
    category = NotificationCategory.IAE_PASS
    subject_template = "approvals/email/prolongation_request/granted/jobseeker_subject.txt"
    body_template = "approvals/email/prolongation_request/granted/jobseeker_body.txt"
