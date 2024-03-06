class BaseNotification:
    REQUIRED = ["can_be_disabled", "name", "category"]

    can_be_disabled = True

    def __init__(self, user, structure=None, /, **kwargs):
        self.user = user
        self.structure = structure
        self.context = kwargs

    def __repr__(self):
        return f"<{self.__class__.__name__} {self.user.email}: {self.name}>"

    def is_manageable_by_user(self):
        return self.can_be_disabled

    def should_send(self):
        if self.is_manageable_by_user():
            return not (
                self.user.notification_settings.for_structure(self.structure)
                .filter(disabled_notifications__notification_class=self.__class__.__name__)
                .exists()
            )
        return True

    def get_context(self):
        return self.validate_context()

    def validate_context(self):
        return self.context
