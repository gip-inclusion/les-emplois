from itou.utils.emails import get_email_message, send_email_messages

from .base import BaseNotification, NotificationMetaclass


__all__ = [
    "EmailNotification",
]


class EmailNotification(BaseNotification, metaclass=NotificationMetaclass):
    subject_template = None
    body_template = None
    from_email = None

    def __init__(self, user, structure, from_email=None, **kwargs):
        self.user = user
        self.structure = structure
        self.from_email = from_email
        self.kwargs = kwargs

    def build(self):
        extra_kwargs = {}
        if self.from_email:
            extra_kwargs["from_email"] = self.from_email

        return get_email_message(
            [self.user.email],
            self.get_context(),
            self.subject_template,
            self.body_template,
            **extra_kwargs,
        )

    def send(self, connection=None):
        if self.should_send():
            return send_email_messages([self.build()], connection)
