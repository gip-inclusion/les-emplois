class BaseNotification:
    REQUIRED = ["can_be_disabled", "name", "category"]

    can_be_disabled = True

    def __init__(self, user, structure=None, forward_from_user=None, /, **kwargs):
        self.user = user
        self.structure = structure
        self.forward_from_user = forward_from_user
        self.context = kwargs

    def __repr__(self):
        return f"<{self.__class__.__name__} {self.user.email}: {self.name}>"

    def is_applicable(self):
        return True

    def is_manageable_by_user(self):
        return self.can_be_disabled and self.is_applicable()

    def should_send(self):
        if not self.user.is_active:
            return False
        if not self.is_applicable():
            return False
        if self.is_manageable_by_user():
            return not (
                self.user.notification_settings.for_structure(self.structure)
                .filter(disabled_notifications__notification_class=self.__class__.__name__)
                .exists()
            )
        return True

    def get_context(self):
        return self.validate_context() | {
            "user": self.user,
            "structure": self.structure,
            "forward_from_user": self.forward_from_user,
        }

    def validate_context(self):
        return self.context
