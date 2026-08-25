from django.conf import settings
from django.urls import reverse

from itou.utils.emails import get_email_message
from itou.utils.urls import get_absolute_url


def notify_backup_code_has_been_used(user):
    email = get_email_message(
        to=[user.email],
        context={"user": user},
        subject="common/emails/used_otp_backup_code_subject.txt",
        body="common/emails/used_otp_backup_code_body.txt",
    )
    email.send()


def notify_mfa_reset_request_init(reset_request, user_orgs):
    """Notify both support AND the user about a 2fa reset request."""
    get_email_message(
        to=[settings.ITOU_EMAIL_CONTACT],
        context={
            "caller": reset_request.user,
            "reset_request": reset_request,
            "admin_url": get_absolute_url(reverse("admin:otp_resetrequest_change", args=(reset_request.pk,))),
        },
        subject="common/emails/mfa_reset_request_init_to_support_subject.txt",
        body="common/emails/mfa_reset_request_init_to_support_body.txt",
    ).send()
    get_email_message(
        to=[reset_request.user.email],
        context={
            "user": reset_request.user,
            "self_cancel_url": get_absolute_url(reverse("otp_views:reset_request_self_cancel")),
        },
        subject="common/emails/mfa_reset_request_init_to_self_subject.txt",
        body="common/emails/mfa_reset_request_init_to_self_body.txt",
    ).send()


def notify_mfa_reset_request_accepted(reset_request):
    """Sent to the 2fa devices owner when an admin accepts the request."""
    email = get_email_message(
        to=[reset_request.user.email],
        context={
            "reset_request": reset_request,
            "self_cancel_url": get_absolute_url(reverse("otp_views:reset_request_self_cancel")),
            "MFA_RESET_LINK_VALIDITY": settings.MFA_RESET_LINK_VALIDITY,
        },
        subject="common/emails/mfa_reset_request_accepted_subject.txt",
        body="common/emails/mfa_reset_request_accepted_body.txt",
    )
    email.send()


def notify_mfa_reset_request_done(reset_request):
    """Sent to the 2fa devices owner they are removed."""
    email = get_email_message(
        to=[reset_request.user.email],
        context={"user": reset_request.user},
        subject="common/emails/mfa_reset_request_done_subject.txt",
        body="common/emails/mfa_reset_request_done_body.txt",
    )
    email.send()


def notify_mfa_reset_request_denied(reset_request):
    """Sent to the 2fa devices owner when an admin rejects the request."""
    email = get_email_message(
        to=[reset_request.user.email],
        context={"user": reset_request.user},
        subject="common/emails/mfa_reset_request_denied_subject.txt",
        body="common/emails/mfa_reset_request_denied_body.txt",
    )
    email.send()
