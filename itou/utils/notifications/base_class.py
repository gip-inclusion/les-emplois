from django.db.models import Q


class NotificationBase:

    SEND_TO_ALL_DEFAULT = True

    def __init__(self, recipients_qs=None):
        self.recipients_qs = recipients_qs

    @property
    def email(self):
        raise NotImplementedError

    @property
    def name(self):
        raise NotImplementedError

    @property
    def recipients_emails(self):
        raise NotImplementedError

    @property
    def subscribed_lookup(self):
        """
        Return a Q object to be used in a queryset to get only subscribed recipients.
        For example:
          Cls.objects.filter(self.subscribed_lookup)
        """
        filters = {f"notifications__{self.name}__subscribed": True}
        return Q(**filters)

    @property
    def unset_lookup(self):
        filters = {f"notifications__{self.name}__isnull": True}
        return Q(**filters)

    def add_notification_key(self, recipient):
        if not recipient.notifications.get(self.name):
            recipient.notifications[self.name] = {}

    def is_subscribed(self, recipient):
        if recipient.notifications.get(self.name):
            return recipient.notifications[self.name]["subscribed"]
        return False

    def send(self):
        return self.email.send()

    def subscribe(self, recipient):
        self.add_notification_key(recipient=recipient)
        recipient.notifications[self.name]["subscribed"] = True
        recipient.save()

    def unsubscribe(self, recipient):
        self.add_notification_key(recipient=recipient)
        recipient.notifications[self.name]["subscribed"] = False
        recipient.save()

    def get_recipients(self):
        if self.SEND_TO_ALL_DEFAULT:
            self._subscribe_unset_recipients()

        return self.recipients_qs.filter(self.subscribed_lookup)

    def _subscribe_unset_recipients(self):
        unset_recipients = self.recipients_qs.filter(self.unset_lookup)
        if unset_recipients:
            for recipient in unset_recipients:
                self.subscribe(recipient=recipient)
