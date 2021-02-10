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
    - Override the `__init__` method as well as `email` and `recipients_email` properties. Provide a Notification.NAME.

    Live example:
    - Model: itou/siaes/models.py > SiaeMembership
    - Notifications: itou/job_applications/notifications.py
    """

    NAME = None  # Notification name as well as key used to store notification preference in the database.
    SEND_TO_UNSET_RECIPIENTS = True  # If recipients didn't express any preference, do we send it anyway?

    def __init__(
        self,
        recipients_qs: [
            SiaeMembershipQuerySet,
        ],
    ):
        """
        `recipients_qs`: Django QuerySet leading to this notification recipients.
        We should be able to perform a `filter()` with it.
        """
        self.recipients_qs = recipients_qs

    def send(self):
        self.email.send()

    def get_recipients(self):
        return self.recipients_qs.filter(self.subscribed_lookup)

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
        filters = {f"notifications__{self.NAME}__subscribed": True}
        query = Q(**filters)
        if self.SEND_TO_UNSET_RECIPIENTS:
            query = Q(query | self.unset_lookup)

        return query

    @property
    def unset_lookup(self):
        """
        Get recipients who didn't express any preference concerning this notification.
        Return a Q object to be used in a queryset.
        For example:
          Cls.objects.filter(self.unset_lookup)
        """
        filters = {f"notifications__{self.NAME}__isnull": True}
        return Q(**filters)

    @classmethod
    def is_subscribed(cls, recipient):
        name = cls.NAME
        if cls.SEND_TO_UNSET_RECIPIENTS and not recipient.notifications.get(name):
            return True
        return recipient.notifications.get(name) and recipient.notifications[name]["subscribed"]

    @classmethod
    def subscribe_bulk(cls, recipients, *args, **kwargs):
        subscribed_recipients = []
        for recipient in recipients.all():
            recipient = cls.subscribe(recipient=recipient, save=False, *args, **kwargs)
            subscribed_recipients.append(recipient)
        recipients.model.objects.bulk_update(subscribed_recipients, ["notifications"])

    @classmethod
    def subscribe(cls, recipient, save=True):
        recipient.notifications.setdefault(cls.NAME, {})["subscribed"] = True
        if save:
            recipient.save()
        return recipient

    @classmethod
    def unsubscribe(cls, recipient):
        recipient.notifications.setdefault(cls.NAME, {})["subscribed"] = False
        recipient.save()
