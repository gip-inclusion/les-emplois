from itou.communications import NotificationCategory, registry as notifications_registry
from itou.communications.dispatch import EmailNotification


@notifications_registry.register
class EmailConfirmationNotification(EmailNotification):
    name = "Confirmation d'adresse e-mail"
    category = NotificationCategory.ACCOUNT
    subject_template = "account/email/email_confirmation_subject.txt"
    body_template = "account/email/email_confirmation_message.txt"
    can_be_disabled = False


@notifications_registry.register
class EmailConfirmationSignupNotification(EmailConfirmationNotification):
    name = "Confirmation d'adresse e-mail pendant inscription"
    subject_template = "account/email/email_confirmation_signup_subject.txt"
    body_template = "account/email/email_confirmation_signup_message.txt"
