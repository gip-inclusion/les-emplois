from django.core.exceptions import ImproperlyConfigured

from itou.communications import registry as notifications_registry
from tests.utils.test import TestCase

from .utils import FakeNotificationClassesMixin


class NotificationRegistryTest(FakeNotificationClassesMixin, TestCase):
    def test_required_attributes_validation_one(self):
        expected_message = "ErrorNotification must define the following attrs: 'category'."
        with self.assertRaisesMessage(ImproperlyConfigured, expected_message):

            @notifications_registry.register
            class ErrorNotification(self.TestNotification):
                name = "Test"

    def test_required_attributes_validation_many(self):
        expected_message = "ErrorNotification must define the following attrs: 'name', 'category'."
        with self.assertRaisesMessage(ImproperlyConfigured, expected_message):

            @notifications_registry.register
            class ErrorNotification(self.TestNotification):
                pass

    def test_required_attributes_validation_others(self):
        expected_message = "ErrorNotification must define the following attrs: 'name', 'required_attribute'."
        with self.assertRaisesMessage(ImproperlyConfigured, expected_message):

            @notifications_registry.register
            class ErrorNotification(self.TestOtherNotification):
                category = "Test"

    def test_name_conflict(self):
        @notifications_registry.register
        class ConflictNotification(self.TestNotification):
            name = "Test"
            category = "Test"

        self.addCleanup(notifications_registry.unregister, ConflictNotification)

        expected_message = "'ConflictNotification' is already registered"
        with self.assertRaisesMessage(NameError, expected_message):

            @notifications_registry.register
            class ConflictNotification(self.TestNotification):  # noqa: F811
                name = "Test"
                category = "Test"
