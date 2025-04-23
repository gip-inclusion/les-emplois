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


@notifications_registry.register
class JobSeekerCreatedByProxyNotification(EmailNotification):
    name = "Invitation à accéder au compte d'un nouvel utilisateur créé par un tiers"
    category = NotificationCategory.REGISTRATION
    subject_template = "account/email/email_jobseeker_created_by_third_party_subject.txt"
    body_template = "account/email/email_jobseeker_created_by_third_party_body.txt"
    can_be_disabled = False


@notifications_registry.register
class InactiveJobSeeker(EmailNotification):
    name = "Information avant suppression d'un compte candidat inactif"
    category = NotificationCategory.DELETION
    subject_template = "account/email/email_inactive_user_subject.txt"
    body_template = "account/email/email_inactive_user_body.txt"
    can_be_disabled = False


@notifications_registry.register
class ArchiveJobSeeker(EmailNotification):
    name = "Suppression d'un compte candidat"
    category = NotificationCategory.DELETION
    subject_template = "account/email/email_archive_user_subject.txt"
    body_template = "account/email/email_archive_user_body.txt"
    can_be_disabled = False
