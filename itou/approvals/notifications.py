from itou.utils.emails import get_email_message
from itou.utils.notifications.base_class import NotificationBase


class NewProlongationToAuthorizedPrescriberNotification(NotificationBase):
    """
    Notification sent to the authorized prescriber supposed to have validated the prolongation.
    """

    def __init__(self, prolongation):
        self.prolongation = prolongation

    @property
    def email(self):
        to = [self.prolongation.validated_by.email]
        context = {"prolongation": self.prolongation}
        subject = "approvals/email/new_prolongation_for_prescriber_subject.txt"
        body = "approvals/email/new_prolongation_for_prescriber_body.txt"
        return get_email_message(to, context, subject, body)

    @property
    def name(self):
        return "confirm_prolongation_email"
