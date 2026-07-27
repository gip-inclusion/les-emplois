import pytest
from django.utils import timezone

from itou.otp.utils import (
    _require_otp_for_pro,
    create_placeholder_for_external_totp_device,
    get_user_devices,
    user_can_enroll_otp_device,
    user_can_manage_otp_devices,
    user_is_concerned_by_otp,
    user_uses_external_mfa,
)
from tests.companies.factories import CompanyMembershipFactory
from tests.otp.factories import ItouTOTPDeviceFactory
from tests.prescribers.factories import PrescriberMembershipFactory
from tests.users.factories import EmployerFactory, ItouStaffFactory, JobSeekerFactory, PrescriberFactory


def test_get_user_devices():
    user1 = ItouStaffFactory()
    user2 = ItouStaffFactory()
    deviceB = ItouTOTPDeviceFactory(user=user1, disabled_at=None, name="b")
    deviceA = ItouTOTPDeviceFactory(user=user1, disabled_at=None, name="a")
    ItouTOTPDeviceFactory(user=user1, disabled_at=timezone.now())
    ItouTOTPDeviceFactory(user=user2, disabled_at=None)

    assert get_user_devices(user1) == [deviceA, deviceB]


class TestRequireOtpForPro:
    def test_require_otp_on_some_organizations(self, settings):
        settings.REQUIRE_MFA_FOR_PROS = True
        user = PrescriberFactory(membership=True)
        org = user.prescriberorganization_set.get()
        PrescriberMembershipFactory(user=user)
        CompanyMembershipFactory(user=user)

        assert not _require_otp_for_pro(user)

        settings.REQUIRE_MFA_ON_ORGANIZATION_IDS = {org.id}
        assert _require_otp_for_pro(user)

    def test_require_otp_on_some_companies(self, settings):
        settings.REQUIRE_MFA_FOR_PROS = True
        user = EmployerFactory(membership=True)
        company = user.company_set.get()
        CompanyMembershipFactory(user=user)
        PrescriberMembershipFactory(user=user)

        assert not _require_otp_for_pro(user)

        settings.REQUIRE_MFA_ON_COMPANY_IDS = {company.id}
        assert _require_otp_for_pro(user)


class TestUserIsConcernedByOtp:
    def test_staff_depends_on_setting(self, settings):
        user = ItouStaffFactory()

        settings.REQUIRE_OTP_FOR_STAFF = False
        assert not user_is_concerned_by_otp(user)

        settings.REQUIRE_OTP_FOR_STAFF = True
        assert user_is_concerned_by_otp(user)

    def test_professional_in_allowlisted_organization(self, settings):
        settings.REQUIRE_MFA_FOR_PROS = True
        user = PrescriberFactory(membership=True)
        org = user.prescriberorganization_set.get()

        assert not user_is_concerned_by_otp(user)

        settings.REQUIRE_MFA_ON_ORGANIZATION_IDS = {org.id}
        assert user_is_concerned_by_otp(user)

    def test_professional_in_allowlisted_company(self, settings):
        settings.REQUIRE_MFA_FOR_PROS = True
        user = EmployerFactory(membership=True)
        company = user.company_set.get()

        assert not user_is_concerned_by_otp(user)

        settings.REQUIRE_MFA_ON_COMPANY_IDS = {company.id}
        assert user_is_concerned_by_otp(user)

    def test_job_seeker_is_never_concerned(self, settings):
        settings.REQUIRE_OTP_FOR_STAFF = True
        settings.REQUIRE_MFA_FOR_PROS = True
        assert not user_is_concerned_by_otp(JobSeekerFactory())


class TestUserCanUseOtp:
    """`user_can_enroll_otp_device` and `user_can_manage_otp_devices` gate both the OTP
    section and its menu link."""

    def test_not_concerned_by_otp(self, settings):
        settings.REQUIRE_OTP_FOR_STAFF = False
        user = ItouStaffFactory()
        ItouTOTPDeviceFactory(user=user)

        assert not user_can_enroll_otp_device(user)
        assert not user_can_manage_otp_devices(user)

    def test_concerned_by_otp(self, settings):
        settings.REQUIRE_OTP_FOR_STAFF = True
        user = ItouStaffFactory()

        # Without a device, there is nothing to manage yet
        assert user_can_enroll_otp_device(user)
        assert not user_can_manage_otp_devices(user)

        ItouTOTPDeviceFactory(user=user)
        assert user_can_manage_otp_devices(user)

    def test_disabled_device_is_ignored(self, settings):
        settings.REQUIRE_OTP_FOR_STAFF = True
        user = ItouStaffFactory()
        ItouTOTPDeviceFactory(user=user, disabled_at=timezone.now())

        assert not user_can_manage_otp_devices(user)

    @pytest.mark.parametrize("with_device", [True, False])
    def test_mfa_handled_by_identity_provider(self, settings, with_device):
        settings.REQUIRE_OTP_FOR_STAFF = True
        user = ItouStaffFactory()
        if with_device:
            ItouTOTPDeviceFactory(user=user)
        # Mimic `OtpMiddleware` for a session verified through ProConnect
        user.otp_device = create_placeholder_for_external_totp_device(user)

        assert user_uses_external_mfa(user)
        # It would only confuse the user and our support team
        assert not user_can_enroll_otp_device(user)
        assert not user_can_manage_otp_devices(user)
