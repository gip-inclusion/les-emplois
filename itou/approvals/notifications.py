from itou.common_apps.notifications.base_class import BaseNotification
from itou.utils import constants as base_constants
from itou.utils.emails import get_email_message


class NewProlongationToAuthorizedPrescriberNotification(BaseNotification):
    """
    Notification sent to the authorized prescriber supposed to have validated the prolongation.
    """

    NAME = "confirm_prolongation_email"

    def __init__(self, prolongation):
        self.prolongation = prolongation

    @property
    def email(self):
        to = [self.prolongation.validated_by.email]
        context = {"prolongation": self.prolongation}
        subject = "approvals/email/new_prolongation_for_prescriber_subject.txt"
        body = "approvals/email/new_prolongation_for_prescriber_body.txt"
        return get_email_message(to, context, subject, body, from_email=base_constants.ITOU_EMAIL_PROLONGATION)


class ProlongationRequestCreated(BaseNotification):
    """Notification sent to the authorized prescriber when a prolongation request is created"""

    NAME = "prolongation_request_created"

    def __init__(self, prolongation_request):
        self.prolongation_request = prolongation_request

    @property
    def email(self):
        to = [self.prolongation_request.validated_by.email]
        context = {"prolongation_request": self.prolongation_request}
        subject = "approvals/email/prolongation_request/created_subject.txt"
        body = "approvals/email/prolongation_request/created_body.txt"
        return get_email_message(to, context, subject, body)


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
