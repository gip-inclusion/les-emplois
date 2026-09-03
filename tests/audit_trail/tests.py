import datetime as dt

from django.conf import settings
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from itou.audit_trail.models import AuditTrail, AuditTrailEventType
from itou.www.login.constants import ITOU_SESSION_LOGIN_EMAIL_KEY
from tests.audit_trail.factories import AuditTrailFactory
from tests.users.factories import DEFAULT_PASSWORD, ItouStaffFactory


def test_login(client):
    user = ItouStaffFactory(with_verified_email=True)
    session = client.session
    session[ITOU_SESSION_LOGIN_EMAIL_KEY] = user.email
    session.save()

    before = timezone.now()
    client.post(
        reverse("login:existing_user"),
        data={
            "login": user.email,
            "password": DEFAULT_PASSWORD,
        },
    )
    after = timezone.now()
    trail = AuditTrail.objects.first()
    assert trail.event_type == AuditTrailEventType.CONNECTION
    assert trail.user == user
    assert trail.ip in ("::1", "127.0.0.1")
    assert before <= trail.date <= after


def test_cleanup():
    AuditTrailFactory(event_type=AuditTrailEventType.CONNECTION)
    old = AuditTrailFactory(event_type=AuditTrailEventType.SECOND_FACTOR_RESET_REQUEST)
    old.date = timezone.now() - (settings.AUDIT_TRAIL_STORAGE_DURATION + dt.timedelta(days=15))
    old.save()

    call_command("cleanup_audit_trails")

    assert AuditTrail.objects.count() == 1
    assert AuditTrail.objects.first().event_type == AuditTrailEventType.CONNECTION
