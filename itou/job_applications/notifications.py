from itou.utils.emails import get_email_message


class NewJobApplicationSiaeEmailNotification:
    name = "NewJobApplicationSiaeNotification"

    def __init__(self, job_application=None):
        self.job_application = job_application

    @property
    def email(self):
        to = self._get_recipients()
        context = {"job_application": self.job_application}
        subject = "apply/email/new_for_siae_subject.txt"
        body = "apply/email/new_for_siae_body.txt"
        return get_email_message(to, context, subject, body)

    def send(self):
        return self.email.send()

    def unsubscribe(self, siae_membership):
        siae_membership.notifications["unsubscribed"] += self.name
        siae_membership.save()

    def _get_recipients(self):
        siae = self.job_application.to_siae
        return (
            siae.siaemembership_set.exclude(notifications__unsubscribed__contains=self.name)
            .filter(user__is_active=True)
            .values_list("user__email", flat=True)
        )
