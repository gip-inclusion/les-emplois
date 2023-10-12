from django.db.models import F
from django.urls import reverse

from itou.common_apps.notifications.base_class import BaseNotification
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
            # Limit to the last 10 active colleagues, it should cover the ones dedicated to the IAE and some more.
            .order_by(F("user__last_login").desc(nulls_last=True), "-joined_at", "-pk")[:10]
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


class ProlongationRequestGrantedEmployer(BaseNotification):
    """Notification sent to the employer when the prolongation request is granted"""

    NAME = "prolongation_request_granted_employer"

    def __init__(self, prolongation_request):
        self.prolongation_request = prolongation_request

    @property
    def email(self):
        to = [self.prolongation_request.declared_by.email]
        context = {"prolongation_request": self.prolongation_request}
        subject = "approvals/email/prolongation_request/granted/employer_subject.txt"
        body = "approvals/email/prolongation_request/granted/employer_body.txt"
        return get_email_message(to, context, subject, body)


class ProlongationRequestGrantedJobSeeker(BaseNotification):
    """Notification sent to the jobseeker when the prolongation request is granted"""

    NAME = "prolongation_request_granted_jobseeker"

    def __init__(self, prolongation_request):
        self.prolongation_request = prolongation_request

    @property
    def email(self):
        to = [self.prolongation_request.approval.user.email]
        context = {"prolongation_request": self.prolongation_request}
        subject = "approvals/email/prolongation_request/granted/jobseeker_subject.txt"
        body = "approvals/email/prolongation_request/granted/jobseeker_body.txt"
        return get_email_message(to, context, subject, body)


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
        to = [self.prolongation_request.approval.user.email]
        context = {"prolongation_request": self.prolongation_request}
        subject = "approvals/email/prolongation_request/denied/jobseeker_subject.txt"
        body = "approvals/email/prolongation_request/denied/jobseeker_body.txt"
        return get_email_message(to, context, subject, body)
