from django.db.models import Q

from itou.siaes.models import SiaeMembershipQuerySet


class NotificationBase:
    """
    Base class used in the notifications system.
    - A **notification** represents any transactional email sent to recipients.
    - A **recipient** is, in the real world, an end user that can whether accept or refuse
    to receive a notification. In our code, a recipient represents the model used to store this preference.

    Notifications preferences are stored as a JSON dictionary like this one:
    ```
    {notification.name: {"subscribed": True}}
    ```

    Usage:
    - In the model saving recipients preferences, add a new `JSONField` `notifications`
    and generate a migration
    - Add a `notifications.py` in the app folder
    - In `notifications.py`, create a class for each notification and inherit from NotificationBase
    - Override the `__init__` method as well as `email`, `name` and `recipients_email` properties.

    Live example:
    - Model: itou/siaes/models.py > SiaeMembership
    - Notifications: itou/job_applications/notifications.py
    """

    # If recipients didn't express any preference, do we send it anyway?
    SEND_TO_UNSET_RECIPIENTS = True

    def __init__(
        self,
        recipients_qs: [
            SiaeMembershipQuerySet,
        ],
        *args,
        **kwargs,
    ):
        """
        `recipients_qs`: Django QuerySet leading to this notification recipients.
        We should be able to perform a `filter()` with it.
        """
        self.recipients_qs = recipients_qs

    @property
    def email(self):
        """
        Example email:
        ```
            to = self.recipients_emails
            context = {"job_application": self.job_application}
            subject = "apply/email/new_for_siae_subject.txt"
            body = "apply/email/new_for_siae_body.txt"
            return get_email_message(to, context, subject, body)
        ```
        """
        raise NotImplementedError

    @property
    def name(self):
        """
        Notification name as well as key used to store notification preference in the database.
        Type: string
        """
        raise NotImplementedError

    @property
    def recipients_emails(self):
        """
        List of recipients' email addresses to send `self.email`.
        Type: list of strings
        """
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
        """
        Get recipients who didn't express any preference concerning this notification.
        Return a Q object to be used in a queryset.
        For example:
          Cls.objects.filter(self.unset_lookup)
        """
        filters = {f"notifications__{self.name}__isnull": True}
        return Q(**filters)

    def is_subscribed(self, recipient):
        return recipient.notifications.get(self.name) and recipient.notifications[self.name]["subscribed"]

    def send(self):
        self.email.send()

    def subscribe(self, recipient, save=True):
        recipient.notifications.setdefault(self.name, {})["subscribed"] = True
        if save:
            recipient.save()
        return recipient

    def unsubscribe(self, recipient):
        recipient.notifications.setdefault(self.name, {})["subscribed"] = False
        recipient.save()

    def subscribe_bulk(self, recipients):
        subscribed_recipients = []
        for recipient in recipients.all():
            recipient = self.subscribe(recipient=recipient, save=False)
            subscribed_recipients.append(recipient)
        recipients.model.objects.bulk_update(subscribed_recipients, ["notifications"])

    def get_recipients(self):
        if self.SEND_TO_UNSET_RECIPIENTS:
            self._subscribe_unset_recipients()

        return self.recipients_qs.filter(self.subscribed_lookup)

    def _subscribe_unset_recipients(self):
        unset_recipients = self.recipients_qs.filter(self.unset_lookup)
        if unset_recipients:
            self.subscribe_bulk(unset_recipients)
