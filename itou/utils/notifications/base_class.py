from django.db.models import Q


class NotificationBase:
    @property
    def class_name(self):
        return self.__class__.__name__

    @property
    def subscribed_lookup(self):
        """
        Return a Q object to be used in a queryset to get only subscribed members.
        For example:
          Cls.objects.filter(self.subscribed_lookup)
        """
        filters = {f"notifications__{self.class_name}__subscribed": True}
        return Q(**filters)

    @property
    def email(self):
        raise NotImplementedError

    def send(self):
        return self.email.send()

    def unsubscribe(self, obj):
        """
        Prevent sending a notification to someone.
        `obj` should have a `notifications` field.
        """
        obj.notifications[self.class_name]["subscribed"] = False
        obj.save()

    def _get_recipients(self):
        """
        Override this method using `self.subscribed_lookup`.
        """
        raise NotImplementedError
