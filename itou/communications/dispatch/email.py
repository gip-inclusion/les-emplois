from itou.utils.emails import get_email_message

from .base import BaseNotification


class EmailNotification(BaseNotification):
    REQUIRED = BaseNotification.REQUIRED + ["subject_template", "body_template"]

    def build(self):
        return get_email_message(
            [self.user.email],
            self.get_context(),
            self.subject_template,
            self.body_template,
        )

    def send(self):
        if self.should_send():
            return self.build().send()
