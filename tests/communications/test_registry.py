from functools import partial

import pytest
from django.core.exceptions import ImproperlyConfigured

from itou.communications import registry as notifications_registry
from itou.communications.dispatch.base import BaseNotification


class TestNotificationRegistry:
    def test_required_attributes_validation_one(self):
        expected_message = "ErrorNotification must define the following attrs: 'category'."
        with pytest.raises(ImproperlyConfigured, match=expected_message):

            @notifications_registry.register
            class ErrorNotification(BaseNotification):
                name = "Test"

    def test_required_attributes_validation_many(self):
        expected_message = "ErrorNotification must define the following attrs: 'name', 'category'."
        with pytest.raises(ImproperlyConfigured, match=expected_message):

            @notifications_registry.register
            class ErrorNotification(BaseNotification):
                pass

    def test_required_attributes_validation_others(self):
        expected_message = "ErrorNotification must define the following attrs: 'name', 'required_attribute'."
        with pytest.raises(ImproperlyConfigured, match=expected_message):

            @notifications_registry.register
            class ErrorNotification(BaseNotification):
                REQUIRED = BaseNotification.REQUIRED + ["required_attribute"]
                category = "Test"

    def test_name_conflict(self, request):
        @notifications_registry.register
        class ConflictNotification(BaseNotification):
            name = "Test"
            category = "Test"

        request.addfinalizer(partial(notifications_registry.unregister, ConflictNotification))

        expected_message = "'ConflictNotification' is already registered"
        with pytest.raises(NameError, match=expected_message):

            @notifications_registry.register
            class ConflictNotification(BaseNotification):  # noqa: F811
                name = "Test"
                category = "Test"
