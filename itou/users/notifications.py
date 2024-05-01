from itou.communications import NotificationCategory, registry as notifications_registry
from itou.communications.dispatch import EmailNotification, PrescriberOrEmployerOrLaborInspectorNotification


@notifications_registry.register
class OrganizationActiveMembersReminderNotification(
    PrescriberOrEmployerOrLaborInspectorNotification, EmailNotification
):
    name = "Rappel périodique pour s'assurer que les membres de sa structure sont bien actifs et autorisés"
    category = NotificationCategory.MEMBERS_MANAGEMENT
    subject_template = "users/emails/check_authorized_members_email_subject.txt"
    body_template = "users/emails/check_authorized_members_email_body.txt"
    can_be_disabled = False

    def get_context(self):
        context = super().get_context()
        context["structure"] = self.structure
        return context
