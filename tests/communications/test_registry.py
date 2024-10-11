import pytest
from django.core.exceptions import ImproperlyConfigured

from itou.communications import registry as notifications_registry

from .utils import FakeNotificationClassesMixin


class TestNotificationRegistry(FakeNotificationClassesMixin):
    def setup_method(self):
        super().setup_method()
        self.registries = []

    def teardown_method(self):
        for registry in self.registries:
            notifications_registry.unregister(registry)

    def test_required_attributes_validation_one(self):
        expected_message = "ErrorNotification must define the following attrs: 'category'."
        with pytest.raises(ImproperlyConfigured, match=expected_message):

            @notifications_registry.register
            class ErrorNotification(self.TestNotification):
                name = "Test"

    def test_required_attributes_validation_many(self):
        expected_message = "ErrorNotification must define the following attrs: 'name', 'category'."
        with pytest.raises(ImproperlyConfigured, match=expected_message):

            @notifications_registry.register
            class ErrorNotification(self.TestNotification):
                pass

    def test_required_attributes_validation_others(self):
        expected_message = "ErrorNotification must define the following attrs: 'name', 'required_attribute'."
        with pytest.raises(ImproperlyConfigured, match=expected_message):

            @notifications_registry.register
            class ErrorNotification(self.TestOtherNotification):
                category = "Test"

    def test_name_conflict(self):
        @notifications_registry.register
        class ConflictNotification(self.TestNotification):
            name = "Test"
            category = "Test"

        self.registries.append(ConflictNotification)

        expected_message = "'ConflictNotification' is already registered"
        with pytest.raises(NameError, match=expected_message):

            @notifications_registry.register
            class ConflictNotification(self.TestNotification):  # noqa: F811
                name = "Test"
                category = "Test"
