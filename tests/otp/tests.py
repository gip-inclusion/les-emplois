import datetime as dt

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


def test_2fa_reset_lowest_credibility(monkeypatch):
    user = ItouStaffFactory()
    un_dimanche_2h_du_matin = dt.datetime(2026, 6, 21, 2, tzinfo=dt.UTC)
    with monkeypatch.context() as m:
        m.setattr("django.utils.timezone.now", lambda: un_dimanche_2h_du_matin)
        reset_request = ResetRequestFactory(user=user)
    assert reset_request.estimate_credibility() == 0


def test_2fa_reset_good_credibility(monkeypatch):
    user = ItouStaffFactory()
    un_vendredi_a_midi = dt.datetime(2026, 8, 28, 12, tzinfo=dt.UTC)
    with monkeypatch.context() as m:
        m.setattr("django.utils.timezone.now", lambda: un_vendredi_a_midi)
        reset_request = ResetRequestFactory(user=user)
    assert reset_request.estimate_credibility() == 1


# def test_2fa_cleanup()

## What happens after OTP_RESET_REQUEST_VALIDITY ? Can one open a new request ? Do the request get auto-denied ?
