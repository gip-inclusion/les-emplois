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
