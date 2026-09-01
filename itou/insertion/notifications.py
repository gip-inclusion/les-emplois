from itou.communications import NotificationCategory
from itou.communications.dispatch.email import EmailNotification
from itou.communications.dispatch.utils import JobSeekerNotification, ProfessionalNotification
from itou.job_applications.notifications import notifications_registry


@notifications_registry.register
class OrientationNewForBeneficiaryNotification(JobSeekerNotification, EmailNotification):
    """Notification sent to the beneficiary when an orientation is created."""

    name = "Confirmation d’envoi d’une orientation"
    category = NotificationCategory.ORIENTATION
    subject_template = "insertion/email/new_for_beneficiary_subject.txt"
    body_template = "insertion/email/new_for_beneficiary_body.txt"


@notifications_registry.register
class OrientationNewForSenderNotification(ProfessionalNotification, EmailNotification):
    """Notification sent to the sender when an orientation is created."""

    name = "Confirmation d’envoi d’une orientation"
    category = NotificationCategory.ORIENTATION
    subject_template = "insertion/email/new_for_sender_subject.txt"
    body_template = "insertion/email/new_for_sender_body.txt"

    def get_context(self):
        context = super().get_context()
        orientation = context["orientation"]
        return context | {
            "reminder_one_delay_days": orientation.REMINDER_EMAIL_DELAY_DAYS,
            "reminder_two_delay_days": orientation.REMINDER_EMAIL_DELAY_DAYS * 2,
        }


@notifications_registry.register
class OrientationProcessingForBeneficiaryNotification(JobSeekerNotification, EmailNotification):
    """Notification sent to the beneficiary when an orientation is being processed."""

    name = "Mise à l’étude d’une orientation"
    category = NotificationCategory.ORIENTATION
    subject_template = "insertion/email/processing_for_beneficiary_subject.txt"
    body_template = "insertion/email/processing_for_beneficiary_body.txt"


@notifications_registry.register
class OrientationProcessingForSenderNotification(ProfessionalNotification, EmailNotification):
    """Notification sent to the sender when an orientation is being processed."""

    name = "Mise à l’étude d’une orientation"
    category = NotificationCategory.ORIENTATION
    subject_template = "insertion/email/processing_for_sender_subject.txt"
    body_template = "insertion/email/processing_for_sender_body.txt"

    def get_context(self):
        context = super().get_context()
        orientation = context["orientation"]
        return context | {
            "PROCESSING_EXPIRATION_PERIOD_DAYS": orientation.PROCESSING_EXPIRATION_PERIOD_DAYS,
        }
