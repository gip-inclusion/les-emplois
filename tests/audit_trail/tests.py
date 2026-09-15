import datetime

from django.conf import settings
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from django_otp.oath import TOTP
from freezegun import freeze_time

from itou.audit_trail.models import AuditTrail, AuditTrailEventType
from itou.www.login.constants import ITOU_SESSION_LOGIN_EMAIL_KEY
from tests.audit_trail.factories import AuditTrailFactory
from tests.otp.factories import ItouTOTPDeviceFactory
from tests.users.factories import DEFAULT_PASSWORD, ItouStaffFactory, JobSeekerFactory


def test_login(client):
    user = ItouStaffFactory(with_verified_email=True)
    session = client.session
    session[ITOU_SESSION_LOGIN_EMAIL_KEY] = user.email
    session.save()

    before = timezone.now()
    response = client.post(
        reverse("login:existing_user"),
        data={
            "login": user.email,
            "password": DEFAULT_PASSWORD,
        },
    )
    after = timezone.now()

    assert response.status_code == 302
    event = AuditTrail.objects.first()
    assert event.event_type == AuditTrailEventType.LOG_IN
    assert event.user == user
    assert event.ip in ("::1", "127.0.0.1")
    assert before <= event.timestamp <= after


def test_partial_then_full_login_via_otp(client, settings):
    """Here, OTP is required for staff, we'll only log a partial login until the OTP is given."""
    settings.REQUIRE_OTP_FOR_STAFF = True
    user = ItouStaffFactory(with_verified_email=True)
    device = ItouTOTPDeviceFactory(name="1", user=user)
    totp = TOTP(device.bin_key)
    session = client.session
    session[ITOU_SESSION_LOGIN_EMAIL_KEY] = user.email
    session.save()

    # First, the password, for a partial login:
    response = client.post(
        reverse("login:existing_user"),
        data={
            "login": user.email,
            "password": DEFAULT_PASSWORD,
        },
        follow=True,
    )
    assert response.status_code == 200
    assert {event.event_type for event in AuditTrail.objects.all()} == {AuditTrailEventType.PARTIAL_LOG_IN}

    # Then, the TOTP, for a full login:
    client.post(reverse("otp_views:verify_otp"), data={"otp_token": totp.token()})
    assert {event.event_type for event in AuditTrail.objects.all()} == {
        AuditTrailEventType.PARTIAL_LOG_IN,
        AuditTrailEventType.LOG_IN,
    }


def test_force_login(client):
    """This test is mostly here to ensure that audit_trail does not break force_login.

    probably only usefull while running `pytest -k audit_trail`,
    because a broken force_login would be spotted anyway.
    """
    user = ItouStaffFactory(with_verified_email=True)

    client.force_login(user)

    trail = AuditTrail.objects.first()
    assert trail.event_type == AuditTrailEventType.LOG_IN
    assert trail.user == user


def test_cleanup():
    AuditTrailFactory(event_type=AuditTrailEventType.LOG_IN)
    long_time_ago = timezone.now() - (settings.AUDIT_TRAIL_STORAGE_DURATION + datetime.timedelta(days=15))
    with freeze_time(long_time_ago):
        AuditTrailFactory(event_type=AuditTrailEventType.SECOND_FACTOR_RESET_REQUEST)

    call_command("cleanup_audit_trails")

    assert AuditTrail.objects.count() == 1
    audit_trail = AuditTrail.objects.first()
    assert audit_trail.event_type == AuditTrailEventType.LOG_IN
    assert audit_trail.timestamp != long_time_ago


def test_hijack_do_not_log_user_logged_in(client):
    """A Hijack is not really a login, let’s not log it as a login.

    We may in the future log the hijack in the audit trail though.
    """
    hijacked = JobSeekerFactory()
    hijacker = ItouStaffFactory(is_superuser=True)
    client.force_login(hijacker)

    assert AuditTrail.objects.count() == 1  # (the force_login(hijacker))

    client.post(reverse("hijack:acquire"), {"user_pk": hijacked.pk})

    assert AuditTrail.objects.count() == 1  # (only the force_login(hijacker))
