from django.core import mail
from django.core.exceptions import ImproperlyConfigured

from itou.communications import registry as notifications_registry
from itou.communications.apps import sync_notifications
from itou.communications.dispatch.base import BaseNotification, NotificationMetaclass
from itou.communications.dispatch.email import EmailNotification
from itou.communications.dispatch.utils import (
    EmployerNotification,
    JobSeekerNotification,
    PrescriberNotification,
    PrescriberOrEmployerNotification,
)
from itou.communications.models import Notification, NotificationSettings
from tests.users.factories import EmployerFactory, JobSeekerFactory, PrescriberFactory
from tests.utils.test import TestCase


class FakeNotificationClassesMixin:
    def setUp(self):
        class TestNotification(BaseNotification, metaclass=NotificationMetaclass):
            pass

        class TestOtherNotification(BaseNotification, metaclass=NotificationMetaclass):
            REQUIRED = BaseNotification.REQUIRED + ["required_attribute"]

        self.TestNotification = TestNotification
        self.TestOtherNotification = TestOtherNotification


class NotificationMetaclassTest(FakeNotificationClassesMixin, TestCase):
    def test_required_attributes_validation_one(self):
        expected_message = "ErrorNotification must define the following attrs: 'category'."
        with self.assertRaisesMessage(ImproperlyConfigured, expected_message):

            class ErrorNotification(self.TestNotification):
                name = "Test"

    def test_required_attributes_validation_many(self):
        expected_message = "ErrorNotification must define the following attrs: 'name', 'category'."
        with self.assertRaisesMessage(ImproperlyConfigured, expected_message):

            class ErrorNotification(self.TestNotification):
                pass

    def test_required_attributes_validation_others(self):
        expected_message = "ErrorNotification must define the following attrs: 'name', 'required_attribute'."
        with self.assertRaisesMessage(ImproperlyConfigured, expected_message):

            class ErrorNotification(self.TestOtherNotification):
                category = "Test"


class BaseNotificationTest(FakeNotificationClassesMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.user = PrescriberFactory(email="testuser@beta.gouv.fr", membership=True)
        self.organization = self.user.prescriberorganization_set.first()

        @notifications_registry.register()
        class ManageableNotification(self.TestNotification):
            name = "Manageable"
            category = "Manageable"

        @notifications_registry.register()
        class NonManageableNotification(self.TestNotification):
            name = "NonManageable"
            category = "NonManageable"
            can_be_disabled = False

        self.ManageableNotification = ManageableNotification
        self.NonManageableNotification = NonManageableNotification

        sync_notifications(Notification)

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
        assert repr(self.ManageableNotification(self.user)) == "<Notification testuser@beta.gouv.fr: Manageable>"

    def test_method_get_class_path(self):
        assert (
            self.ManageableNotification(self.user).get_class_path()
            == "tests.communications.test_dispatch.ManageableNotification"
        )

    def test_method_is_manageable_by_user(self):
        assert self.ManageableNotification(self.user, self.organization).is_manageable_by_user()
        assert not self.NonManageableNotification(self.user, self.organization).is_manageable_by_user()

    def test_method_should_send(self):
        # Notifications follow an opt-out logic. So non-manageable can't be disabled and should always be sent
        assert self.NonManageableNotification(self.user, self.organization).should_send()

        # Even if disabled in db
        settings = NotificationSettings.get_or_create(self.user, self.organization)
        settings.disabled_notifications.set(
            [Notification.objects.get(notification_class=self.NonManageableNotification(self.user).get_class_path())]
        )
        assert self.NonManageableNotification(self.user, self.organization).should_send()

        # For manageable notifications, they should be sent by default
        assert self.ManageableNotification(self.user, self.organization).should_send()

        # But should not be sent if disabled
        settings.disabled_notifications.set(
            [Notification.objects.get(notification_class=self.ManageableNotification(self.user).get_class_path())]
        )
        assert not self.ManageableNotification(self.user, self.organization).should_send()

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

        @notifications_registry.register()
        class ManageableNotification(EmailNotification):
            name = "Manageable"
            category = "Manageable"
            subject_template = "layout/base_email_text_subject.txt"
            body_template = "layout/base_email_text_body.txt"

        @notifications_registry.register()
        class NonManageableNotification(EmailNotification):
            name = "NonManageable"
            category = "NonManageable"
            subject_template = "layout/base_email_text_subject.txt"
            body_template = "layout/base_email_text_body.txt"
            can_be_disabled = False

        self.ManageableNotification = ManageableNotification
        self.NonManageableNotification = NonManageableNotification

        sync_notifications(Notification)

    def test_method_build(self):
        email = self.ManageableNotification(self.user, self.organization).build()
        assert email.to == [self.user.email]
        assert "Cet email est envoyé depuis un environnement de démonstration" in email.body

    def test_method_send(self):
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

        class TestJobSeekerNotification(JobSeekerNotification, BaseNotification, metaclass=NotificationMetaclass):
            pass

        class TestEmployerNotification(EmployerNotification, BaseNotification, metaclass=NotificationMetaclass):
            pass

        class TestPrescriberNotification(PrescriberNotification, BaseNotification, metaclass=NotificationMetaclass):
            pass

        class TestPrescriberOrEmployerNotification(
            PrescriberOrEmployerNotification, BaseNotification, metaclass=NotificationMetaclass
        ):
            pass

        self.TestJobSeekerNotification = TestJobSeekerNotification
        self.TestEmployerNotification = TestEmployerNotification
        self.TestPrescriberNotification = TestPrescriberNotification
        self.TestPrescriberOrEmployerNotification = TestPrescriberOrEmployerNotification

    def test_job_seeker_notification_is_manageable_by_user(self):
        assert self.TestJobSeekerNotification(self.job_seeker).is_manageable_by_user()
        assert not self.TestJobSeekerNotification(self.employer, self.employer_structure).is_manageable_by_user()
        assert not self.TestJobSeekerNotification(self.prescriber, self.prescriber_structure).is_manageable_by_user()

    def test_employer_notification_is_manageable_by_user(self):
        assert not self.TestEmployerNotification(self.job_seeker).is_manageable_by_user()
        assert self.TestEmployerNotification(self.employer, self.employer_structure).is_manageable_by_user()
        assert not self.TestEmployerNotification(self.prescriber, self.prescriber_structure).is_manageable_by_user()

    def test_prescriber_notification_is_manageable_by_user(self):
        assert not self.TestPrescriberNotification(self.job_seeker).is_manageable_by_user()
        assert not self.TestPrescriberNotification(self.employer, self.employer_structure).is_manageable_by_user()
        assert self.TestPrescriberNotification(self.prescriber, self.prescriber_structure).is_manageable_by_user()

    def test_prescriber_or_employer_notification_is_manageable_by_user(self):
        assert not self.TestPrescriberOrEmployerNotification(self.job_seeker).is_manageable_by_user()
        assert self.TestPrescriberOrEmployerNotification(
            self.employer, self.employer_structure
        ).is_manageable_by_user()
        assert self.TestPrescriberOrEmployerNotification(
            self.prescriber, self.prescriber_structure
        ).is_manageable_by_user()
