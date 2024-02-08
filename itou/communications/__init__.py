from operator import attrgetter


class NotificationRegistry:
    def __init__(self):
        self._registry = []

    def __iter__(self):
        return iter(sorted(self._registry, key=attrgetter("category", "name")))

    def register(self, notification_class):
        from .dispatch.base import BaseNotification

        if not issubclass(notification_class, BaseNotification):
            raise ValueError("Notification must subclass NotificationBase.")

        self._registry.append(notification_class)
        return notification_class

    def unregister(self, notification_class):
        self._registry.remove(notification_class)

    def register_notification(self):
        def _wrapper(cls):
            return self.register(cls)

        return _wrapper


registry = NotificationRegistry()


def autodiscover():
    """
    Auto discover notifications in any "notifications.py" file in any app.
    """
    from django.utils.module_loading import autodiscover_modules

    autodiscover_modules("notifications", register_to=registry)
