from itou.utils.emails import get_email_message
from itou.utils.notifications.base_class import NotificationBase


class NewJobApplicationSiaeEmailNotification(NotificationBase):
    def __init__(self, job_application=None):
        self.job_application = job_application
        self.siae = job_application.to_siae

    @property
    def email(self):
        to = self._get_recipients()
        context = {"job_application": self.job_application}
        subject = "apply/email/new_for_siae_subject.txt"
        body = "apply/email/new_for_siae_body.txt"
        return get_email_message(to, context, subject, body)

    def _get_recipients(self):
        return self.siae.siaemembership_set.filter(self.subscribed_lookup, user__is_active=True).values_list(
            "user__email", flat=True
        )
