import datetime

import httpx
import pytest
from allauth.account.models import EmailAddress
from django.utils import timezone
from freezegun import freeze_time

from itou.asp.models import RSAAllocation
from itou.companies.models import CompanyMembership
from itou.eligibility.enums import AdministrativeCriteriaKind
from itou.otp.models import ItouStaticDevice, ItouTOTPDevice
from itou.users.models import JobSeekerAssignment, JobSeekerProfile, User
from itou.users.utils import deactivate_users, refresh_rsa_certification
from itou.utils import triggers
from itou.utils.mocks.api_particulier import RESPONSES, ResponseKind
from tests.cities.factories import create_city_saint_andre
from tests.companies.factories import CompanyMembershipFactory
from tests.otp.factories import ItouTOTPDeviceFactory
from tests.users.factories import ItouStaffFactory, JobSeekerAssignmentFactory, JobSeekerFactory


def test_deactivate_professional():
    city = create_city_saint_andre()
    membership = CompanyMembershipFactory(
        user__is_active=True,
        user__first_name="Alice",
        user__last_name="Cooper",
        user__phone=f"06060{city.post_codes[0]}",
        user__address_line_1="8 rue du moulin",
        user__address_line_2="Apt 4B",
        user__post_code=city.post_codes[0],
        user__city="Test City",
        user__coords=city.coords,
        user__insee_city=city,
        user__email=f"test{city.post_codes[0]}@mail.com",
        user__with_verified_email=True,
        user__with_password=True,
        is_active=True,
        is_admin=True,
        updated_by=ItouStaffFactory(),
    )
    employer = membership.user
    ItouTOTPDeviceFactory(user=employer)
    ItouStaticDevice.objects.create(user=employer, name="static")
    assignment_without_organization = JobSeekerAssignmentFactory(professional=employer)
    assignment_with_organization = JobSeekerAssignmentFactory(professional=employer, company=membership.company)
    username_before_deactivation = employer.username
    updated_at_before_deactivation = membership.updated_at

    with triggers.fake_context():
        deactivate_users([employer])

    employer = User.objects.get(pk=employer.pk)
    assert not employer.is_active
    assert employer.email is None
    assert employer.phone == ""
    assert employer.address_line_1 == ""
    assert employer.address_line_2 == ""
    assert employer.post_code == ""
    assert employer.city == ""
    assert employer.coords is None
    assert employer.insee_city is None
    assert employer.first_name == "Alice"
    assert employer.last_name == "Cooper"
    assert employer.username == f"old_{employer.pk}_{username_before_deactivation}"
    assert not employer.has_usable_password()
    assert not EmailAddress.objects.filter(user=employer).exists()
    assert not ItouTOTPDevice.objects.filter(user=employer).exists()
    assert not ItouStaticDevice.objects.filter(user=employer).exists()
    assert not JobSeekerAssignment.objects.filter(pk=assignment_without_organization.pk).exists()
    assert JobSeekerAssignment.objects.filter(pk=assignment_with_organization.pk).exists()

    membership = CompanyMembership.include_inactive.get(user=employer)
    assert not membership.is_active
    assert not membership.is_admin
    assert membership.updated_by is None
    assert membership.updated_at > updated_at_before_deactivation


def test_deactivate_job_seeker():
    city = create_city_saint_andre()
    job_seeker = JobSeekerFactory(
        is_active=True,
        first_name="Alice",
        last_name="Cooper",
        phone=f"06060{city.post_codes[0]}",
        address_line_1="8 rue du moulin",
        address_line_2="Apt 4B",
        post_code=city.post_codes[0],
        city="Test City",
        coords=city.coords,
        insee_city=city,
        email=f"test{city.post_codes[0]}@mail.com",
        with_verified_email=True,
        with_password=True,
    )
    ItouTOTPDeviceFactory(user=job_seeker)
    ItouStaticDevice.objects.create(user=job_seeker, name="static")
    assignment = JobSeekerAssignmentFactory(job_seeker=job_seeker)
    username_before_deactivation = job_seeker.username

    with triggers.fake_context():
        deactivate_users([job_seeker])

    job_seeker = User.objects.get(pk=job_seeker.pk)
    assert not job_seeker.is_active
    assert job_seeker.email is None
    assert job_seeker.phone == ""
    assert job_seeker.address_line_1 == ""
    assert job_seeker.address_line_2 == ""
    assert job_seeker.post_code == ""
    assert job_seeker.city == ""
    assert job_seeker.coords is None
    assert job_seeker.insee_city is None
    assert job_seeker.first_name == "Alice"
    assert job_seeker.last_name == "Cooper"
    assert job_seeker.username == f"old_{job_seeker.pk}_{username_before_deactivation}"
    assert not job_seeker.has_usable_password()
    assert not EmailAddress.objects.filter(user=job_seeker).exists()
    assert not ItouTOTPDevice.objects.filter(user=job_seeker).exists()
    assert not ItouStaticDevice.objects.filter(user=job_seeker).exists()
    # Assignments are only removed on the professional side
    assert JobSeekerAssignment.objects.filter(pk=assignment.pk).exists()


def test_deactivate_users_updated_by():
    membership = CompanyMembershipFactory(is_active=True, updated_by=None)
    staff_user = ItouStaffFactory()

    with triggers.fake_context():
        deactivate_users([membership.user], updated_by=staff_user)

    membership = CompanyMembership.include_inactive.get(pk=membership.pk)
    assert not membership.is_active
    assert membership.updated_by == staff_user


class TestRefreshRSACertification:
    RSA_URL = "https://fake-api-particulier.com/v3/dss/revenu_solidarite_active/identite"

    def mock_rsa(self, respx_mock, response_kind):
        response = RESPONSES[AdministrativeCriteriaKind.RSA][response_kind]
        return respx_mock.get(self.RSA_URL).respond(response["status_code"], json=response["json"])

    @freeze_time("2025-01-06 11:11:11")
    def test_beneficiary(self, api_particulier_settings, respx_mock):
        self.mock_rsa(respx_mock, ResponseKind.CERTIFIED)
        job_seeker = JobSeekerFactory(born_in_france=True)

        refresh_rsa_certification(job_seeker)

        profile = JobSeekerProfile.objects.get(pk=job_seeker.jobseeker_profile.pk)
        assert profile.rsa_certified_beneficiary is True
        assert profile.rsa_certified_start_date == datetime.date(2024, 8, 1)
        assert profile.rsa_certification_checked_at == timezone.now()
        # The ASP fields are left untouched.
        assert profile.has_rsa_allocation == RSAAllocation.NO
        assert profile.rsa_allocation_since == ""

    @freeze_time("2025-01-06 11:11:11")
    def test_not_beneficiary(self, api_particulier_settings, respx_mock):
        self.mock_rsa(respx_mock, ResponseKind.NOT_CERTIFIED)
        job_seeker = JobSeekerFactory(born_in_france=True)

        refresh_rsa_certification(job_seeker)

        profile = JobSeekerProfile.objects.get(pk=job_seeker.jobseeker_profile.pk)
        assert profile.rsa_certified_beneficiary is False
        assert profile.rsa_certified_start_date is None
        assert profile.rsa_certification_checked_at == timezone.now()

    @freeze_time("2025-01-06 11:11:11")
    def test_not_found_means_no_subsidy(self, api_particulier_settings, respx_mock):
        self.mock_rsa(respx_mock, ResponseKind.NOT_FOUND)
        job_seeker = JobSeekerFactory(born_in_france=True)

        refresh_rsa_certification(job_seeker)

        profile = JobSeekerProfile.objects.get(pk=job_seeker.jobseeker_profile.pk)
        assert profile.rsa_certified_beneficiary is False
        assert profile.rsa_certified_start_date is None
        assert profile.rsa_certification_checked_at == timezone.now()

    @freeze_time("2025-01-06 11:11:11")
    def test_unprocessable_content_leaves_rights_unknown(self, api_particulier_settings, respx_mock):
        self.mock_rsa(respx_mock, ResponseKind.UNPROCESSABLE_CONTENT)
        job_seeker = JobSeekerFactory(born_in_france=True)

        refresh_rsa_certification(job_seeker)

        profile = JobSeekerProfile.objects.get(pk=job_seeker.jobseeker_profile.pk)
        assert profile.rsa_certified_beneficiary is None
        assert profile.rsa_certified_start_date is None
        # The identity was checked, don’t hammer the API with the same parameters.
        assert profile.rsa_certification_checked_at == timezone.now()

    @pytest.mark.parametrize("status_code", [409, 429, 500, 502, 503])
    def test_api_error_is_swallowed_and_retried_later(self, api_particulier_settings, respx_mock, status_code, caplog):
        respx_mock.get(self.RSA_URL).respond(status_code, json={})
        job_seeker = JobSeekerFactory(born_in_france=True)

        refresh_rsa_certification(job_seeker)

        profile = JobSeekerProfile.objects.get(pk=job_seeker.jobseeker_profile.pk)
        assert profile.rsa_certified_beneficiary is None
        assert profile.rsa_certification_checked_at is None
        assert f"API Particulier answered with HTTP {status_code}" in caplog.text

    def test_unreachable_api_is_swallowed(self, api_particulier_settings, respx_mock, caplog):
        respx_mock.get(self.RSA_URL).mock(side_effect=httpx.ConnectTimeout)
        job_seeker = JobSeekerFactory(born_in_france=True)

        refresh_rsa_certification(job_seeker)

        profile = JobSeekerProfile.objects.get(pk=job_seeker.jobseeker_profile.pk)
        assert profile.rsa_certification_checked_at is None
        assert "API Particulier is unreachable" in caplog.text

    def test_skipped_when_api_is_not_configured(self, respx_mock):
        job_seeker = JobSeekerFactory(born_in_france=True)

        refresh_rsa_certification(job_seeker)

        assert len(respx_mock.calls) == 0
        assert job_seeker.jobseeker_profile.rsa_certification_checked_at is None

    def test_skipped_when_required_information_is_missing(self, api_particulier_settings, respx_mock):
        # No birthdate: the API cannot be queried at all.
        job_seeker = JobSeekerFactory(jobseeker_profile__birthdate=None)

        refresh_rsa_certification(job_seeker)

        assert len(respx_mock.calls) == 0
        assert job_seeker.jobseeker_profile.rsa_certification_checked_at is None

    @freeze_time("2025-01-06 11:11:11")
    def test_skipped_when_checked_less_than_24_hours_ago(self, api_particulier_settings, respx_mock):
        self.mock_rsa(respx_mock, ResponseKind.CERTIFIED)
        job_seeker = JobSeekerFactory(
            born_in_france=True,
            jobseeker_profile__rsa_certified_beneficiary=False,
            jobseeker_profile__rsa_certification_checked_at=timezone.now() - datetime.timedelta(hours=23),
        )

        refresh_rsa_certification(job_seeker)

        assert len(respx_mock.calls) == 0
        profile = JobSeekerProfile.objects.get(pk=job_seeker.jobseeker_profile.pk)
        assert profile.rsa_certified_beneficiary is False

    @freeze_time("2025-01-06 11:11:11")
    def test_refreshed_when_checked_more_than_24_hours_ago(self, api_particulier_settings, respx_mock):
        self.mock_rsa(respx_mock, ResponseKind.CERTIFIED)
        job_seeker = JobSeekerFactory(
            born_in_france=True,
            jobseeker_profile__rsa_certified_beneficiary=False,
            jobseeker_profile__rsa_certification_checked_at=timezone.now() - datetime.timedelta(hours=25),
        )

        refresh_rsa_certification(job_seeker)

        assert len(respx_mock.calls) == 1
        profile = JobSeekerProfile.objects.get(pk=job_seeker.jobseeker_profile.pk)
        assert profile.rsa_certified_beneficiary is True
        assert profile.rsa_certified_start_date == datetime.date(2024, 8, 1)
