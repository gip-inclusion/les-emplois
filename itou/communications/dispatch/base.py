from django.core.exceptions import ImproperlyConfigured


class NotificationMetaclass(type):
    def __new__(cls, name, bases, attrs, **kwargs):
        new_class = super().__new__(cls, name, bases, attrs, **kwargs)

        # Ensure initialization is only performed for concrete notification classes.
        parents = [b for b in bases if isinstance(b, NotificationMetaclass)]
        if not parents:
            return new_class

        if not hasattr(new_class, "name"):
            raise ImproperlyConfigured(f"{name} must define 'name'.")
        if not hasattr(new_class, "category"):
            raise ImproperlyConfigured(f"{name} must define 'category'.")

        return new_class


class BaseNotification:
    user = None
    structure = None
    can_be_disabled = True
    name = None
    category = None
    kwargs = {}

    def __repr__(self):
        return f"<Notification {self.user.email}: {self.name}>"

    @classmethod
    def get_class_path(cls):
        return f"{cls.__module__}.{cls.__name__}"

    def is_manageable_by_user(self):
        return self.can_be_disabled

    def should_send(self):
        if self.is_manageable_by_user():
            return (
                self.user.notification_settings.for_structure(self.structure)
                .filter(disabled_notifications__notification_class=self.get_class_path())
                .exists()
            )
        return True

    def get_context(self):
        return self.check_context(self.kwargs)

    def check_context(self, context):
        return context
