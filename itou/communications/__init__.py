from operator import attrgetter

from django.utils.module_loading import autodiscover_modules


class NotificationRegistry:
    def __init__(self):
        self._registry = []

    def __iter__(self):
        return iter(sorted(self._registry, key=attrgetter("category", "name")))

    def register(self, notification_class=None):
        def inner(notification_class):
            from .dispatch.base import BaseNotification

            if not issubclass(notification_class, BaseNotification):
                raise ValueError("Notification must subclass BaseNotification.")

            self._registry.append(notification_class)
            return notification_class

        if callable(notification_class):
            return inner(notification_class)
        else:
            return inner

    def unregister(self, notification_class):
        self._registry.remove(notification_class)


registry = NotificationRegistry()


def autodiscover():
    """
    Auto discover notifications in any "notifications.py" file in any app.
    """
    autodiscover_modules("notifications", register_to=registry)
