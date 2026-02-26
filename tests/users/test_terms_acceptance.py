import datetime

import pytest
from django.utils import timezone
from freezegun import freeze_time

from tests.users.factories import (
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
)


class TestMustAcceptTerms:
    @pytest.mark.parametrize("accepted", [True, False])
    @pytest.mark.parametrize(
        "factory",
        [
            ItouStaffFactory,
            PrescriberFactory,
            EmployerFactory,
            LaborInspectorFactory,
            JobSeekerFactory,
        ],
    )
    def test_only_pro_must_accept_terms(self, factory, accepted):
        user = factory(terms_accepted_at=timezone.now() if accepted else None)
        is_concerned_by_terms = factory in (PrescriberFactory, EmployerFactory, LaborInspectorFactory)
        assert user.must_accept_terms() is (is_concerned_by_terms and not accepted)

    @pytest.mark.parametrize("has_accepted", [True, False])
    @pytest.mark.parametrize("factory", [PrescriberFactory, EmployerFactory, LaborInspectorFactory])
    def test_must_accept_terms_depends_on_terms_date(self, factory, has_accepted, mocker):
        terms_datetime = timezone.make_aware(datetime.datetime(2026, 2, 19, 0, 0))
        mocker.patch("itou.users.models.get_latest_terms_datetime", return_value=terms_datetime)  # tested elsewhere
        accepted_at = terms_datetime + datetime.timedelta(days=1 if has_accepted else -1)
        user = factory(terms_accepted_at=accepted_at)
        assert user.must_accept_terms() != has_accepted


class TestSetTermsAccepted:
    @pytest.mark.parametrize("factory", [PrescriberFactory, EmployerFactory, LaborInspectorFactory])
    def test_updates_terms_accepted_at_for_professional_users(self, factory, mocker):
        user = factory()
        now = timezone.make_aware(datetime.datetime(2026, 2, 19, 9, 10))
        save_mock = mocker.patch.object(user, "save")
        with freeze_time(now):
            user.set_terms_accepted()
        assert user.terms_accepted_at == now
        save_mock.assert_called_once_with(update_fields=["terms_accepted_at"])

    @pytest.mark.parametrize("factory", [ItouStaffFactory, JobSeekerFactory])
    def test_does_nothing_for_non_professional_users(self, factory):
        now = timezone.make_aware(datetime.datetime(2026, 2, 19, 9, 10))
        user = factory()
        with freeze_time(now):
            user.set_terms_accepted()
        assert user.terms_accepted_at is None
