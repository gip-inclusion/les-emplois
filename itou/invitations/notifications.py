from itou.communications import registry
from itou.communications.dispatch import EmailNotification, PrescriberOrEmployerNotification


@registry.register_notification()
class InvitationAcceptedNotification(PrescriberOrEmployerNotification, EmailNotification):
    """Notification sent to a user when the invitation is accepted"""

    name = "Invitation acceptée"
    category = "Gestion des collaborateurs"
    subject_template = "invitations_views/email/accepted_notif_sender_subject.txt"
    body_template = "invitations_views/email/accepted_notif_establishment_sender_body.txt"
