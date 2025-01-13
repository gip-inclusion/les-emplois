import re

import pytest

from itou.communications import registry as notifications_registry
from itou.communications.apps import sync_notifications
from itou.communications.dispatch.base import BaseNotification
from itou.communications.dispatch.email import EmailNotification
from itou.communications.dispatch.utils import (
    EmployerNotification,
    JobSeekerNotification,
    PrescriberNotification,
    PrescriberOrEmployerNotification,
    WithStructureMixin,
)
from itou.communications.models import NotificationRecord, NotificationSettings
from tests.companies.factories import CompanyMembershipFactory
from tests.prescribers.factories import PrescriberMembershipFactory
from tests.users.factories import EmployerFactory, JobSeekerFactory, PrescriberFactory


class TestBaseNotification:
    @pytest.fixture
    def manageable_notification(self):
        @notifications_registry.register
        class ManageableNotification(BaseNotification):
            name = "Manageable"
            category = "Manageable"

        yield ManageableNotification
        notifications_registry.unregister(ManageableNotification)

    @pytest.fixture
    def manageable_non_applicable_notification(self):
        @notifications_registry.register
        class ManageableNonApplicableNotification(BaseNotification):
            name = "Manageable, non-applicable"
            category = "Manageable, non-applicable"

            def is_applicable(self):
                return False

        yield ManageableNonApplicableNotification
        notifications_registry.unregister(ManageableNonApplicableNotification)

    @pytest.fixture
    def non_manageable_notification(self):
        @notifications_registry.register
        class NonManageableNotification(BaseNotification):
            name = "NonManageable"
            category = "NonManageable"
            can_be_disabled = False

        yield NonManageableNotification
        notifications_registry.unregister(NonManageableNotification)

    @pytest.fixture
    def non_manageable_non_applicable_notification(self):
        @notifications_registry.register
        class NonManageableNonApplicableNotification(BaseNotification):
            name = "NonManageable, non-applicable"
            category = "NonManageable, non-applicable"
            can_be_disabled = False

            def is_applicable(self):
                return False

        yield NonManageableNonApplicableNotification
        notifications_registry.unregister(NonManageableNonApplicableNotification)

    def setup_method(self):
        self.user = PrescriberFactory(email="testuser@beta.gouv.fr", membership=True)
        self.organization = self.user.prescriberorganization_set.first()

    def test_method_init(self):
        with pytest.raises(
            TypeError, match=re.escape("BaseNotification.__init__() missing 1 required positional argument: 'user")
        ):
            BaseNotification()

        notification = BaseNotification(self.user)
        assert notification.user == self.user
        assert notification.structure is None
        assert notification.context == {}

        notification = BaseNotification(self.user, "structure")
        assert notification.user == self.user
        assert notification.structure == "structure"
        assert notification.context == {}

        notification = BaseNotification(self.user, "structure", kw1=1, kw2=2)
        assert notification.user == self.user
        assert notification.structure == "structure"
        assert notification.context == {"kw1": 1, "kw2": 2}

    def test_method_repr(self, manageable_notification):
        assert repr(manageable_notification(self.user)) == "<ManageableNotification testuser@beta.gouv.fr: Manageable>"

    def test_method_is_manageable_by_user(
        self,
        manageable_notification,
        manageable_non_applicable_notification,
        non_manageable_notification,
        non_manageable_non_applicable_notification,
    ):
        assert manageable_notification(self.user, self.organization).is_manageable_by_user()
        assert not manageable_non_applicable_notification(self.user, self.organization).is_manageable_by_user()
        assert not non_manageable_notification(self.user, self.organization).is_manageable_by_user()
        assert not non_manageable_non_applicable_notification(self.user, self.organization).is_manageable_by_user()

    def test_method_is_applicable(
        self,
        manageable_notification,
        manageable_non_applicable_notification,
        non_manageable_notification,
        non_manageable_non_applicable_notification,
    ):
        assert manageable_notification(self.user, self.organization).is_applicable()
        assert not manageable_non_applicable_notification(self.user, self.organization).is_applicable()
        assert non_manageable_notification(self.user, self.organization).is_applicable()
        assert not non_manageable_non_applicable_notification(self.user, self.organization).is_applicable()

    def test_method_should_send(
        self,
        manageable_notification,
        manageable_non_applicable_notification,
        non_manageable_notification,
        non_manageable_non_applicable_notification,
    ):
        sync_notifications(NotificationRecord)

        # Notifications follow an opt-out logic. So non-manageable can't be disabled by the user
        # and should always be sent unless they're non-applicable
        assert non_manageable_notification(self.user, self.organization).should_send()
        assert not non_manageable_non_applicable_notification(self.user, self.organization).should_send()

        # Even if disabled in db
        settings, _ = NotificationSettings.get_or_create(self.user, self.organization)
        settings.disabled_notifications.set(
            [
                NotificationRecord.objects.get(
                    notification_class=non_manageable_notification(self.user).__class__.__name__
                ),
                NotificationRecord.objects.get(
                    notification_class=non_manageable_non_applicable_notification(self.user).__class__.__name__
                ),
            ]
        )
        assert non_manageable_notification(self.user, self.organization).should_send()
        assert not non_manageable_non_applicable_notification(self.user, self.organization).should_send()

        # For manageable notifications, they should be sent unless they're non-applicable
        assert manageable_notification(self.user, self.organization).should_send()
        assert not manageable_non_applicable_notification(self.user, self.organization).should_send()

        # But should not be sent if disabled
        settings.disabled_notifications.set(
            [
                NotificationRecord.objects.get(
                    notification_class=manageable_notification(self.user).__class__.__name__
                ),
                NotificationRecord.objects.get(
                    notification_class=manageable_non_applicable_notification(self.user).__class__.__name__
                ),
            ]
        )
        assert not manageable_notification(self.user, self.organization).should_send()
        assert not manageable_non_applicable_notification(self.user, self.organization).should_send()

    def test_method_get_context(self):
        assert BaseNotification(self.user, self.organization).get_context() == {
            "user": self.user,
            "structure": self.organization,
            "forward_from_user": None,
        }
        assert BaseNotification(self.user, self.organization, kw1=1, kw2=2).get_context() == {
            "user": self.user,
            "structure": self.organization,
            "forward_from_user": None,
            "kw1": 1,
            "kw2": 2,
        }

    def test_method_validate_context(self):
        assert BaseNotification(self.user, self.organization).validate_context() == {}
        assert BaseNotification(self.user, self.organization, kw1=1, kw2=2).validate_context() == {
            "kw1": 1,
            "kw2": 2,
        }


class TestEmailNotification:
    @pytest.fixture
    def email_notification(self):
        @notifications_registry.register
        class FakeEmailNotification(EmailNotification):
            name = "Manageable"
            category = "Manageable"
            subject_template = "layout/base_email_text_subject.txt"
            body_template = "layout/base_email_text_body.txt"

        yield FakeEmailNotification
        notifications_registry.unregister(FakeEmailNotification)

    def setup_method(self):
        self.user = PrescriberFactory(email="testuser@beta.gouv.fr", membership=True)
        self.organization = self.user.prescriberorganization_set.first()

    def test_method_build(self, email_notification):
        email = email_notification(self.user, self.organization).build()
        assert email.to == [self.user.email]
        assert "Cet email est envoyé depuis un environnement de démonstration" in email.body

    def test_method_send(self, email_notification, django_capture_on_commit_callbacks, mailoutbox):
        with django_capture_on_commit_callbacks(execute=True):
            email_notification(self.user, self.organization).send()
        assert len(mailoutbox) == 1
        assert mailoutbox[0].to == [self.user.email]
        assert "Cet email est envoyé depuis un environnement de démonstration" in mailoutbox[0].body

    def test_method_send_for_prescriber_that_left_his_org(
        self, email_notification, django_capture_on_commit_callbacks, mailoutbox, caplog
    ):
        self.user.prescribermembership_set.update(is_active=False)

        admin_1 = PrescriberMembershipFactory(
            user=PrescriberFactory(),
            organization=self.organization,
            is_admin=True,
        ).user
        admin_2 = PrescriberMembershipFactory(
            user=PrescriberFactory(),
            organization=self.organization,
            is_admin=True,
        ).user
        PrescriberMembershipFactory(
            user=PrescriberFactory(),
            organization=self.organization,
            is_admin=False,
        )

        with django_capture_on_commit_callbacks(execute=True):
            email_notification(self.user, self.organization).send()

        assert caplog.messages == ["Send email copy to admin, admin_count=2"]
        assert len(mailoutbox) == 3
        assert set(sum((mail.to for mail in mailoutbox), [])) == {admin_1.email, admin_2.email, self.user.email}
        assert (
            f"Vous recevez cet e-mail parce que l'utilisateur {self.user.get_full_name()} ({self.user.email})"
            " ne fait plus partie de votre organisation." in mailoutbox[0].body
        )
        assert (
            f"Vous recevez cet e-mail parce que l'utilisateur {self.user.get_full_name()} ({self.user.email})"
            " ne fait plus partie de votre organisation." in mailoutbox[1].body
        )

    def test_method_send_for_employer_that_left_his_company(
        self, email_notification, django_capture_on_commit_callbacks, mailoutbox, caplog
    ):
        user = EmployerFactory(with_company=True)
        company = user.companymembership_set.first().company
        user.companymembership_set.update(is_active=False)

        admin_1 = CompanyMembershipFactory(
            user=EmployerFactory(),
            company=company,
            is_admin=True,
        ).user
        admin_2 = CompanyMembershipFactory(
            user=EmployerFactory(),
            company=company,
            is_admin=True,
        ).user
        CompanyMembershipFactory(
            user=EmployerFactory(),
            company=company,
            is_admin=False,
        )

        with django_capture_on_commit_callbacks(execute=True):
            email_notification(user, company).send()

        assert caplog.messages == ["Send email copy to admin, admin_count=2"]
        assert len(mailoutbox) == 3
        assert set(sum((mail.to for mail in mailoutbox), [])) == {admin_1.email, admin_2.email, user.email}
        assert (
            f"Vous recevez cet e-mail parce que l'utilisateur {user.get_full_name()} ({user.email})"
            " ne fait plus partie de votre structure." in mailoutbox[0].body
        )
        assert (
            f"Vous recevez cet e-mail parce que l'utilisateur {user.get_full_name()} ({user.email})"
            " ne fait plus partie de votre structure." in mailoutbox[1].body
        )

    def test_method_send_for_inactive_user(self, email_notification, django_capture_on_commit_callbacks, mailoutbox):
        self.user.is_active = False
        self.user.save()
        with django_capture_on_commit_callbacks(execute=True):
            email_notification(self.user, self.organization).send()
        assert len(mailoutbox) == 0

        # But we still forward it if the user left his organozation
        admin = PrescriberMembershipFactory(
            user=PrescriberFactory(),
            organization=self.organization,
            is_admin=True,
        ).user

        with django_capture_on_commit_callbacks(execute=True):
            email_notification(self.user, self.organization).send()
        assert len(mailoutbox) == 1
        assert mailoutbox[0].to == [admin.email]


class TestProfiledNotification:
    def setup_method(self):
        self.job_seeker = JobSeekerFactory()
        self.employer = EmployerFactory(with_company=True)
        self.employer_structure = self.employer.company_set.first()
        self.prescriber = PrescriberFactory(membership=True)
        self.prescriber_structure = self.prescriber.prescriberorganization_set.first()
        self.prescriber_single = PrescriberFactory(membership=False)

        class TestJobSeekerNotification(JobSeekerNotification, BaseNotification):
            pass

        class TestEmployerNotification(EmployerNotification, BaseNotification):
            pass

        class TestPrescriberNotification(PrescriberNotification, BaseNotification):
            pass

        class TestPrescriberWithStructureNotification(WithStructureMixin, PrescriberNotification, BaseNotification):
            pass

        class TestPrescriberOrEmployerNotification(PrescriberOrEmployerNotification, BaseNotification):
            pass

        class TestPrescriberOrEmployerWithStructureNotification(
            WithStructureMixin, PrescriberOrEmployerNotification, BaseNotification
        ):
            pass

        self.TestJobSeekerNotification = TestJobSeekerNotification
        self.TestEmployerNotification = TestEmployerNotification
        self.TestPrescriberNotification = TestPrescriberNotification
        self.TestPrescriberOrEmployerNotification = TestPrescriberOrEmployerNotification
        self.TestPrescriberWithStructureNotification = TestPrescriberWithStructureNotification
        self.TestPrescriberOrEmployerWithStructureNotification = TestPrescriberOrEmployerWithStructureNotification

    def test_job_seeker_notification_is_manageable_by_user(self):
        assert self.TestJobSeekerNotification(self.job_seeker).is_manageable_by_user()
        assert not self.TestJobSeekerNotification(self.employer, self.employer_structure).is_manageable_by_user()
        assert not self.TestJobSeekerNotification(self.prescriber, self.prescriber_structure).is_manageable_by_user()
        assert not self.TestJobSeekerNotification(self.prescriber_single).is_manageable_by_user()

    def test_employer_notification_is_manageable_by_user(self):
        assert not self.TestEmployerNotification(self.job_seeker).is_manageable_by_user()
        assert self.TestEmployerNotification(self.employer, self.employer_structure).is_manageable_by_user()
        assert not self.TestEmployerNotification(self.prescriber, self.prescriber_structure).is_manageable_by_user()
        assert not self.TestEmployerNotification(self.prescriber_single).is_manageable_by_user()

    def test_prescriber_notification_is_manageable_by_user(self):
        assert not self.TestPrescriberNotification(self.job_seeker).is_manageable_by_user()
        assert not self.TestPrescriberNotification(self.employer, self.employer_structure).is_manageable_by_user()
        assert self.TestPrescriberNotification(self.prescriber, self.prescriber_structure).is_manageable_by_user()
        assert self.TestPrescriberNotification(self.prescriber_single).is_manageable_by_user()

    def test_prescriber_with_structure_notification_is_manageable_by_user(self):
        assert not self.TestPrescriberWithStructureNotification(self.job_seeker).is_manageable_by_user()
        assert not self.TestPrescriberWithStructureNotification(
            self.employer, self.employer_structure
        ).is_manageable_by_user()
        assert self.TestPrescriberWithStructureNotification(
            self.prescriber, self.prescriber_structure
        ).is_manageable_by_user()
        assert not self.TestPrescriberWithStructureNotification(self.prescriber_single).is_manageable_by_user()

    def test_prescriber_or_employer_notification_is_manageable_by_user(self):
        assert not self.TestPrescriberOrEmployerNotification(self.job_seeker).is_manageable_by_user()
        assert self.TestPrescriberOrEmployerNotification(
            self.employer, self.employer_structure
        ).is_manageable_by_user()
        assert self.TestPrescriberOrEmployerNotification(
            self.prescriber, self.prescriber_structure
        ).is_manageable_by_user()
        assert self.TestPrescriberOrEmployerNotification(self.prescriber_single).is_manageable_by_user()

    def test_prescriber_or_employer_with_structure_notification_is_manageable_by_user(self):
        assert not self.TestPrescriberOrEmployerWithStructureNotification(self.job_seeker).is_manageable_by_user()
        assert self.TestPrescriberOrEmployerWithStructureNotification(
            self.employer, self.employer_structure
        ).is_manageable_by_user()
        assert self.TestPrescriberOrEmployerWithStructureNotification(
            self.prescriber, self.prescriber_structure
        ).is_manageable_by_user()
        assert not self.TestPrescriberOrEmployerWithStructureNotification(
            self.prescriber_single
        ).is_manageable_by_user()
