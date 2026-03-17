from itou.communications import NotificationCategory, registry as notifications_registry
from itou.communications.dispatch import EmailNotification, ProfessionalNotification, WithStructureMixin


@notifications_registry.register
class InvitationAcceptedNotification(WithStructureMixin, ProfessionalNotification, EmailNotification):
    """Notification sent to a user when the invitation is accepted"""

    name = "Demande d'ajout acceptée"
    category = NotificationCategory.MEMBERS_MANAGEMENT
    subject_template = "invitations_views/email/accepted_notif_sender_subject.txt"
    body_template = "invitations_views/email/accepted_notif_establishment_sender_body.txt"
