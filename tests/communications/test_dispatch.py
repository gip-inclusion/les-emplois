from django.core import mail

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
from tests.users.factories import EmployerFactory, JobSeekerFactory, PrescriberFactory
from tests.utils.test import TestCase

from .utils import FakeNotificationClassesMixin


class BaseNotificationTest(FakeNotificationClassesMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.user = PrescriberFactory(email="testuser@beta.gouv.fr", membership=True)
        self.organization = self.user.prescriberorganization_set.first()

        @notifications_registry.register
        class ManageableNotification(self.TestNotification):
            name = "Manageable"
            category = "Manageable"

        self.addCleanup(notifications_registry.unregister, ManageableNotification)

        @notifications_registry.register
        class ManageableNonApplicableNotification(self.TestNotification):
            name = "Manageable, non-applicable"
            category = "Manageable, non-applicable"

            def is_applicable(self):
                return False

        self.addCleanup(notifications_registry.unregister, ManageableNonApplicableNotification)

        @notifications_registry.register
        class NonManageableNotification(self.TestNotification):
            name = "NonManageable"
            category = "NonManageable"
            can_be_disabled = False

        self.addCleanup(notifications_registry.unregister, NonManageableNotification)

        @notifications_registry.register
        class NonManageableNonApplicableNotification(self.TestNotification):
            name = "NonManageable, non-applicable"
            category = "NonManageable, non-applicable"
            can_be_disabled = False

            def is_applicable(self):
                return False

        self.addCleanup(notifications_registry.unregister, NonManageableNonApplicableNotification)

        self.ManageableNotification = ManageableNotification
        self.ManageableNonApplicableNotification = ManageableNonApplicableNotification
        self.NonManageableNotification = NonManageableNotification
        self.NonManageableNonApplicableNotification = NonManageableNonApplicableNotification

        sync_notifications(NotificationRecord)

    def test_method_init(self):
        with self.assertRaisesMessage(
            TypeError, "BaseNotification.__init__() missing 1 required positional argument: 'user'"
        ):
            self.TestNotification()

        notification = self.TestNotification(self.user)
        assert notification.user == self.user
        assert notification.structure is None
        assert notification.context == {}

        notification = self.TestNotification(self.user, "structure")
        assert notification.user == self.user
        assert notification.structure == "structure"
        assert notification.context == {}

        notification = self.TestNotification(self.user, "structure", kw1=1, kw2=2)
        assert notification.user == self.user
        assert notification.structure == "structure"
        assert notification.context == {"kw1": 1, "kw2": 2}

    def test_method_repr(self):
        assert (
            repr(self.ManageableNotification(self.user))
            == "<ManageableNotification testuser@beta.gouv.fr: Manageable>"
        )

    def test_method_is_manageable_by_user(self):
        assert self.ManageableNotification(self.user, self.organization).is_manageable_by_user()
        assert not self.ManageableNonApplicableNotification(self.user, self.organization).is_manageable_by_user()
        assert not self.NonManageableNotification(self.user, self.organization).is_manageable_by_user()
        assert not self.NonManageableNonApplicableNotification(self.user, self.organization).is_manageable_by_user()

    def test_method_is_applicable(self):
        assert self.ManageableNotification(self.user, self.organization).is_applicable()
        assert not self.ManageableNonApplicableNotification(self.user, self.organization).is_applicable()
        assert self.NonManageableNotification(self.user, self.organization).is_applicable()
        assert not self.NonManageableNonApplicableNotification(self.user, self.organization).is_applicable()

    def test_method_should_send(self):
        # Notifications follow an opt-out logic. So non-manageable can't be disabled by the user
        # and should always be sent unless they're non-applicable
        assert self.NonManageableNotification(self.user, self.organization).should_send()
        assert not self.NonManageableNonApplicableNotification(self.user, self.organization).should_send()

        # Even if disabled in db
        settings, _ = NotificationSettings.get_or_create(self.user, self.organization)
        settings.disabled_notifications.set(
            [
                NotificationRecord.objects.get(
                    notification_class=self.NonManageableNotification(self.user).__class__.__name__
                ),
                NotificationRecord.objects.get(
                    notification_class=self.NonManageableNonApplicableNotification(self.user).__class__.__name__
                ),
            ]
        )
        assert self.NonManageableNotification(self.user, self.organization).should_send()
        assert not self.NonManageableNonApplicableNotification(self.user, self.organization).should_send()

        # For manageable notifications, they should be sent unless they're non-applicable
        assert self.ManageableNotification(self.user, self.organization).should_send()
        assert not self.ManageableNonApplicableNotification(self.user, self.organization).should_send()

        # But should not be sent if disabled
        settings.disabled_notifications.set(
            [
                NotificationRecord.objects.get(
                    notification_class=self.ManageableNotification(self.user).__class__.__name__
                ),
                NotificationRecord.objects.get(
                    notification_class=self.ManageableNonApplicableNotification(self.user).__class__.__name__
                ),
            ]
        )
        assert not self.ManageableNotification(self.user, self.organization).should_send()
        assert not self.ManageableNonApplicableNotification(self.user, self.organization).should_send()

    def test_method_get_context(self):
        assert self.ManageableNotification(self.user, self.organization).get_context() == {}
        assert self.ManageableNotification(self.user, self.organization, kw1=1, kw2=2).get_context() == {
            "kw1": 1,
            "kw2": 2,
        }

    def test_method_validate_context(self):
        assert self.ManageableNotification(self.user, self.organization).validate_context() == {}
        assert self.ManageableNotification(self.user, self.organization, kw1=1, kw2=2).validate_context() == {
            "kw1": 1,
            "kw2": 2,
        }


class EmailNotificationTest(FakeNotificationClassesMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.user = PrescriberFactory(email="testuser@beta.gouv.fr", membership=True)
        self.organization = self.user.prescriberorganization_set.first()

        @notifications_registry.register
        class ManageableNotification(EmailNotification):
            name = "Manageable"
            category = "Manageable"
            subject_template = "layout/base_email_text_subject.txt"
            body_template = "layout/base_email_text_body.txt"

        self.addCleanup(notifications_registry.unregister, ManageableNotification)

        @notifications_registry.register
        class NonManageableNotification(EmailNotification):
            name = "NonManageable"
            category = "NonManageable"
            subject_template = "layout/base_email_text_subject.txt"
            body_template = "layout/base_email_text_body.txt"
            can_be_disabled = False

        self.addCleanup(notifications_registry.unregister, NonManageableNotification)

        self.ManageableNotification = ManageableNotification

        sync_notifications(NotificationRecord)

    def test_method_build(self):
        email = self.ManageableNotification(self.user, self.organization).build()
        assert email.to == [self.user.email]
        assert "Cet email est envoyé depuis un environnement de démonstration" in email.body

    def test_method_send(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.ManageableNotification(self.user, self.organization).send()
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [self.user.email]
        assert "Cet email est envoyé depuis un environnement de démonstration" in mail.outbox[0].body


class ProfiledNotificationTest(TestCase):
    def setUp(self):
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
