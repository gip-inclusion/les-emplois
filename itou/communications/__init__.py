from enum import StrEnum
from operator import attrgetter

from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import autodiscover_modules


class NotificationCategory(StrEnum):
    IAE_PASS = "PASS IAE"
    MEMBERS_MANAGEMENT = "Gestion des collaborateurs"
    JOB_APPLICATION = "Candidature"


class NotificationRegistry:
    def __init__(self):
        self._registry = []

    def __iter__(self):
        return iter(sorted(self._registry, key=attrgetter("category", "name")))

    def register(self, notification_class):
        from .dispatch.base import BaseNotification

        if not issubclass(notification_class, BaseNotification):
            raise ValueError("Notification must subclass BaseNotification.")

        if notification_class.__name__ in [registered.__name__ for registered in self]:
            raise NameError(f"'{notification_class.__name__}' is already registered.")

        missing_required_attrs = []
        for attr_name in getattr(notification_class, "REQUIRED", []):
            if not hasattr(notification_class, attr_name):
                missing_required_attrs.append(attr_name)

        if missing_required_attrs:
            missing_required_attrs_str = ", ".join([f"'{attr_name}'" for attr_name in missing_required_attrs])
            raise ImproperlyConfigured(
                f"{notification_class.__name__} must define the following attrs: {missing_required_attrs_str}."
            )

        self._registry.append(notification_class)
        return notification_class

    def unregister(self, notification_class):
        self._registry.remove(notification_class)


registry = NotificationRegistry()


def autodiscover():
    """
    Auto discover notifications in any "notifications.py" file in any app.
    """
    autodiscover_modules("notifications", register_to=registry)
