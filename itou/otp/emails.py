from itou.common_apps.organizations.utils import get_org_admins
from itou.utils.emails import get_email_message


def notify_backup_code_has_been_used(user):
    email = get_email_message(
        to=[user.email],
        context={"user": user},
        subject="common/emails/used_otp_backup_code_subject.txt",
        body="common/emails/used_otp_backup_code_body.txt",
    )
    email.send()


def notify_reset_request_init(user, user_orgs):
    """Notify both org admins AND the user about a 2fa reset request."""
    admins = get_org_admins(user_orgs, user)
    for admin in admins:
        email = get_email_message(
            to=[admin.email],
            context={"caller": user, "user": admin},
            subject="common/emails/2fa_reset_request_init_subject.txt",
            body="common/emails/2fa_reset_request_init_body.txt",
        )
        email.send()
    email = get_email_message(
        to=[user.email],
        context={"user": user, "org_has_admins": bool(admins)},
        subject="common/emails/2fa_reset_request_init_to_self_subject.txt",
        body="common/emails/2fa_reset_request_init_to_self_body.txt",
    )
    email.send()


def notify_2fa_reset_request_accepted(user, reset_link):
    """Sent to the 2fa devices owner when an admin accepts the request."""
    email = get_email_message(
        to=[user.email],
        context={"user": user, "reset_link": reset_link},
        subject="common/emails/2fa_reset_request_accepted_subject.txt",
        body="common/emails/2fa_reset_request_accepted_body.txt",
    )
    email.send()


def notify_2fa_reset_request_done(user):
    """Sent to the 2fa devices owner they are removed."""
    email = get_email_message(
        to=[user.email],
        context={"user": user},
        subject="common/emails/2fa_reset_request_done_subject.txt",
        body="common/emails/2fa_reset_request_done_body.txt",
    )
    email.send()


def notify_2fa_reset_request_denied(user):
    """Sent to the 2fa devices owner when an admin rejects the request."""
    email = get_email_message(
        to=[user.email],
        context={"user": user},
        subject="common/emails/2fa_reset_request_denied_subject.txt",
        body="common/emails/2fa_reset_request_denied_body.txt",
    )
    email.send()
