from django.conf import settings

from itou.communications import NotificationCategory, registry as notifications_registry
from itou.communications.dispatch import EmailNotification, PrescriberOrEmployerOrLaborInspectorNotification
from itou.utils.urls import get_absolute_url


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
class JobSeekerCreatedByProxyNotificationForGPS(EmailNotification):
    name = "Invitation à accéder au compte d'un nouvel utilisateur créé par un tiers - GPS"
    category = NotificationCategory.REGISTRATION
    subject_template = "account/email/email_jobseeker_created_by_third_party_for_gps_subject.txt"
    body_template = "account/email/email_jobseeker_created_by_third_party_for_gps_body.txt"
    can_be_disabled = False

    def get_build_extra(self):
        return {"from_email": settings.GPS_CONTACT_EMAIL}


@notifications_registry.register
class InactiveUser(EmailNotification):
    name = "Information avant suppression d'un compte utilisateur inactif"
    category = NotificationCategory.DELETION
    subject_template = "account/email/email_inactive_user_subject.txt"
    body_template = "account/email/email_inactive_user_body.txt"
    can_be_disabled = False

    def get_context(self):
        context = super().get_context()
        context["base_url"] = get_absolute_url()
        return context


@notifications_registry.register
class ArchiveUser(EmailNotification):
    name = "Suppression d'un compte utilisateur"
    category = NotificationCategory.DELETION
    subject_template = "account/email/email_archive_user_subject.txt"
    body_template = "account/email/email_archive_user_body.txt"
    can_be_disabled = False

    def get_context(self):
        context = super().get_context()
        context["base_url"] = get_absolute_url()
        return context
