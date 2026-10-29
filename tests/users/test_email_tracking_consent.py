import pytest
from django.utils import timezone
from freezegun import freeze_time

from tests.users.factories import ItouStaffFactory, JobSeekerFactory, ProfessionalFactory


@pytest.mark.parametrize("answered", [True, False])
@pytest.mark.parametrize(
    "factory, concerned",
    [
        (ItouStaffFactory, False),
        (ProfessionalFactory, True),
        (JobSeekerFactory, True),
    ],
)
def test_must_answer_email_tracking_consent(factory, concerned, answered):
    user = factory(email_tracking_consent_updated_at=timezone.now() if answered else None)
    assert user.must_answer_email_tracking_consent is (concerned and not answered)


@freeze_time("2026-09-28")
@pytest.mark.parametrize("consent", [True, False])
def test_set_email_tracking_consent(consent):
    user = JobSeekerFactory(email_tracking_consent=not consent, email_tracking_consent_updated_at=None)
    user.set_email_tracking_consent(consent)
    assert user.email_tracking_consent is consent
    assert user.email_tracking_consent_updated_at == timezone.now()
