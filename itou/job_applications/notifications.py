from itou.utils.emails import get_email_message
from itou.utils.notifications.base_class import NotificationBase


class NewJobApplicationSiaeEmailNotification(NotificationBase):
    def __init__(self, job_application):
        active_memberships = job_application.to_siae.siaemembership_set.filter(is_active=True, user__is_active=True)
        super().__init__(recipients_qs=active_memberships)
        self.job_application = job_application
        self.siae = job_application.to_siae

    @property
    def email(self):
        to = self.recipients_emails
        context = {"job_application": self.job_application}
        subject = "apply/email/new_for_siae_subject.txt"
        body = "apply/email/new_for_siae_body.txt"
        return get_email_message(to, context, subject, body)

    @property
    def name(self):
        """
        Key used to store notification subscription preference.
        """
        return "new_job_application_siae_email"

    @property
    def recipients_emails(self):
        return self.get_recipients().values_list("user__email", flat=True)
