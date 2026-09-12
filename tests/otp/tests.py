import datetime

from django.conf import settings
from django.core.management import call_command
from freezegun import freeze_time

from itou.otp.enums import ResetRequestState
from itou.otp.models import ResetRequestTransitionLog
from tests.otp.factories import ItouTOTPDeviceFactory, ResetRequestFactory
from tests.users.factories import ItouStaffFactory


def test_2fa_reset_mail_sent_when_request_accepted(settings, mailoutbox, django_capture_on_commit_callbacks):
    settings.REQUIRE_OTP_FOR_STAFF = True
    device = ItouTOTPDeviceFactory(name="1")
    reset_request = ResetRequestFactory(user=device.user)

    with django_capture_on_commit_callbacks(execute=True):  # To run _async_send_message huey task
        reset_request.accept()
    assert len(mailoutbox) == 1


def test_2fa_reset_resend_link(settings, mailoutbox, django_capture_on_commit_callbacks):
    settings.REQUIRE_OTP_FOR_STAFF = True
    device = ItouTOTPDeviceFactory(name="1")
    reset_request = ResetRequestFactory(user=device.user)

    with django_capture_on_commit_callbacks(execute=True):  # To run _async_send_message huey task
        reset_request.accept()
        reset_request.resend()
    assert len(mailoutbox) == 2


def test_2fa_reset_lowest_credibility():
    user = ItouStaffFactory()
    un_dimanche_2h_du_matin = datetime.datetime(2026, 6, 21, 2, tzinfo=datetime.UTC)
    with freeze_time(un_dimanche_2h_du_matin):
        reset_request = ResetRequestFactory(user=user)
    assert reset_request.is_suspicious


def test_2fa_reset_good_credibility():
    user = ItouStaffFactory()
    un_vendredi_a_midi = datetime.datetime(2026, 8, 28, 12, tzinfo=datetime.UTC)
    with freeze_time(un_vendredi_a_midi):
        reset_request = ResetRequestFactory(user=user)
    assert not reset_request.is_suspicious


def test_2fa_reset_close_expired_command():
    long_ago = datetime.datetime(1984, 4, 4, tzinfo=datetime.UTC)
    with freeze_time(long_ago):
        reset_request = ResetRequestFactory()
    call_command("close_expired_2fa_reset_requests")
    reset_request.refresh_from_db()
    assert reset_request.state == ResetRequestState.DENIED
    assert ResetRequestTransitionLog.objects.filter(reset_request=reset_request, msg="Request expired.").exists()


def test_2fa_reset_close_expired_command_keeps_fresh_requests():
    reset_request = ResetRequestFactory()
    call_command("close_expired_2fa_reset_requests")
    reset_request.refresh_from_db()
    assert reset_request.state == ResetRequestState.PENDING
    assert ResetRequestTransitionLog.objects.count() == 0


def test_2fa_reset_close_expired_command_grace_for_freshly_accepted_requests():
    """Let's say we have and old requeset that should be closed by the
    command, but it was **just** accepted by an admin.

    In this case the request should survive to avoid the surprise of a
    user having an error while clicking a freshly received link.
    """
    created_at = datetime.datetime(1984, 4, 4, tzinfo=datetime.UTC)
    should_expires_at = created_at + settings.OTP_RESET_REQUEST_VALIDITY
    right_before_expiration = should_expires_at - datetime.timedelta(hours=1)
    right_after_expiration = should_expires_at + datetime.timedelta(hours=1)
    long_after_expiration = should_expires_at + settings.OTP_RESET_LINK_VALIDITY + datetime.timedelta(hours=1)

    with freeze_time(created_at):
        reset_request = ResetRequestFactory()

    with freeze_time(right_before_expiration):
        # Accepting the request right before its expiration pushes its lifetime a bit:
        reset_request.accept()

    with freeze_time(right_after_expiration):
        # Will not close the request because it has just been accepted:
        call_command("close_expired_2fa_reset_requests")

    # Check the request has not been closed:
    reset_request.refresh_from_db()
    assert reset_request.state == ResetRequestState.ACCEPTED

    with freeze_time(long_after_expiration):
        # Will close the request because it's really too old this time:
        call_command("close_expired_2fa_reset_requests")

    reset_request.refresh_from_db()
    assert reset_request.state == ResetRequestState.DENIED
    assert ResetRequestTransitionLog.objects.filter(reset_request=reset_request, msg="Request expired.").exists()


def test_2fa_reset_close_expired_command_grace_for_freshly_resent_requests():
    """Let's say we have and old requeset that should be closed by the
    command, but it was accepted and a link for it was **just** resent
    by an admin.

    In this case the request should survive to avoid the surprise of a
    user having an error while clicking a freshly received link.
    """
    created_at = datetime.datetime(1984, 4, 4, tzinfo=datetime.UTC)
    should_expires_at = created_at + settings.OTP_RESET_REQUEST_VALIDITY
    right_before_expiration = should_expires_at - datetime.timedelta(hours=1)
    right_after_expiration = should_expires_at + datetime.timedelta(hours=1)
    long_after_expiration = should_expires_at + settings.OTP_RESET_LINK_VALIDITY + datetime.timedelta(hours=1)

    with freeze_time(created_at):
        reset_request = ResetRequestFactory()
        reset_request.accept()

    with freeze_time(right_before_expiration):
        # Re-sending a link make this request survive a bit after its expiration:
        reset_request.resend()

    with freeze_time(right_after_expiration):
        # This will not close the request because a link from it has just been resent:
        call_command("close_expired_2fa_reset_requests")

    # Check the request has not been closed:
    reset_request.refresh_from_db()
    assert reset_request.state == ResetRequestState.ACCEPTED

    with freeze_time(long_after_expiration):
        # Will close the request because it's really too old this time:
        call_command("close_expired_2fa_reset_requests")

    reset_request.refresh_from_db()
    assert reset_request.state == ResetRequestState.DENIED
    assert ResetRequestTransitionLog.objects.filter(reset_request=reset_request, msg="Request expired.").exists()
