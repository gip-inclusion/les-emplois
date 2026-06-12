from django.utils import timezone

from itou.otp.utils import _require_otp_for_pro, get_user_devices
from tests.companies.factories import CompanyMembershipFactory
from tests.otp.factories import ItouTOTPDeviceFactory
from tests.prescribers.factories import PrescriberMembershipFactory
from tests.users.factories import EmployerFactory, ItouStaffFactory, PrescriberFactory


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
