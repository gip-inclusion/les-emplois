from django.core.exceptions import ImproperlyConfigured


class NotificationMetaclass(type):
    def __new__(cls, name, bases, attrs, **kwargs):
        new_class = super().__new__(cls, name, bases, attrs, **kwargs)

        # Ensure initialization is only performed for concrete notification classes.
        parents = [b for b in bases if isinstance(b, NotificationMetaclass)]
        if not parents:
            return new_class

        missing_required_attrs = []
        for attr_name in getattr(new_class, "REQUIRED", []):
            if not hasattr(new_class, attr_name):
                missing_required_attrs.append(attr_name)

        if missing_required_attrs:
            missing_required_attrs_str = ", ".join([f"'{attr_name}'" for attr_name in missing_required_attrs])
            raise ImproperlyConfigured(f"{name} must define the following attrs: {missing_required_attrs_str}.")

        return new_class


class BaseNotification:
    REQUIRED = ["can_be_disabled", "name", "category"]

    can_be_disabled = True

    def __init__(self, user, structure=None, /, **kwargs):
        self.user = user
        self.structure = structure
        self.context = kwargs

    def __repr__(self):
        return f"<Notification {self.user.email}: {self.name}>"

    @classmethod
    def get_class_path(cls):
        return f"{cls.__module__}.{cls.__name__}"

    def is_manageable_by_user(self):
        return self.can_be_disabled

    def should_send(self):
        if self.is_manageable_by_user():
            return not (
                self.user.notification_settings.for_structure(self.structure)
                .filter(disabled_notifications__notification_class=self.get_class_path())
                .exists()
            )
        return True

    def get_context(self):
        return self.validate_context()

    def validate_context(self):
        return self.context
