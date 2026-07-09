import datetime

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from django_otp.oath import TOTP

from itou.otp.utils import _require_otp_for_pro, get_user_devices, verify_token_for_user
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


class TestVerifyTokenForUser:
    def test_matches_and_does_not_penalise_earlier_devices(self):
        # `device_a` sorts before `device_b`, so it is tried (and fails) first
        user = ItouStaffFactory()
        device_a = ItouTOTPDeviceFactory(user=user, name="a")
        device_b = ItouTOTPDeviceFactory(user=user, name="b")

        matched = verify_token_for_user(user, TOTP(device_b.bin_key).token())

        assert matched == device_b
        device_a.refresh_from_db()
        # The collateral increment from the failed try on `device_a` was rolled back
        assert device_a.throttling_failure_count == 0

    def test_preserves_prior_failures_on_earlier_devices(self):
        user = ItouStaffFactory()
        device_a = ItouTOTPDeviceFactory(user=user, name="a")
        device_b = ItouTOTPDeviceFactory(user=user, name="b")
        # `device_a` already has genuine prior failures, but the throttle window has
        # elapsed (old timestamp), so `verify_token` will run and increment it again.
        device_a.throttling_failure_count = 2
        device_a.throttling_failure_timestamp = timezone.now() - datetime.timedelta(days=1)
        device_a.save()

        matched = verify_token_for_user(user, TOTP(device_b.bin_key).token())

        assert matched == device_b
        device_a.refresh_from_db()
        assert device_a.throttling_failure_count == 2  # Restored to its prior count

    def test_wrong_token_returns_none_and_throttles_every_device(self):
        user = ItouStaffFactory()
        device_a = ItouTOTPDeviceFactory(user=user, name="a")
        device_b = ItouTOTPDeviceFactory(user=user, name="b")

        assert verify_token_for_user(user, "000000") is None

        for device in (device_a, device_b):
            device.refresh_from_db()
            assert device.throttling_failure_count == 1

    def test_no_devices_returns_none(self):
        user = ItouStaffFactory()
        assert verify_token_for_user(user, "000000") is None

    def test_verification_query_count_is_bounded(self, django_assert_num_queries):
        """Guards against an N+1 in the rollback.

        Matching the last of three devices runs a fixed set of queries, regardless of
        how many earlier devices were tried:
          2 SAVEPOINT + RELEASE SAVEPOINT  (the helper's transaction.atomic)
          1 SELECT ... FOR UPDATE        (load + lock the user's devices)
          2 UPDATEs                      (django_otp throttle_increment on devices a, b)
          1 UPDATE                       (success: throttle_reset on device c)
          1 UPDATE                       (single bulk_update rolling back a, b)
        A per-device rollback would push this to 8.
        """
        user = ItouStaffFactory()
        # `device_c` is the match, `device_a` and `device_b` are tried (and fail) first,
        # so both get a collateral throttle increment that must be rolled back
        ItouTOTPDeviceFactory(user=user, name="a")
        ItouTOTPDeviceFactory(user=user, name="b")
        device_c = ItouTOTPDeviceFactory(user=user, name="c")
        token = TOTP(device_c.bin_key).token()

        with django_assert_num_queries(7), CaptureQueriesContext(connection) as ctx:
            assert verify_token_for_user(user, token) == device_c
        sqls = [q["sql"] for q in ctx.captured_queries]
        # The user's devices are loaded once, under a row lock (race mitigation)
        assert sum("FOR UPDATE" in sql for sql in sqls) == 1
        # The two collateral increments are rolled back with one `bulk_update`
        restore_updates = [
            sql for sql in sqls if sql.startswith("UPDATE") and "throttling_failure_count" in sql and "WHEN" in sql
        ]
        assert len(restore_updates) == 1


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
