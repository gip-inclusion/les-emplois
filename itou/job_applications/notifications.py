from django.db.models import Q

from itou.utils.emails import get_email_message
from itou.utils.notifications.base_class import NotificationBase


class NewSpontaneousJobAppEmployersNotification(NotificationBase):
    NAME = "new_spontaneous_job_application_employers_email"

    def __init__(self, job_application):
        self.job_application = job_application
        active_memberships = job_application.to_siae.siaemembership_set.active()
        super().__init__(recipients_qs=active_memberships)

    @property
    def email(self):
        to = self.recipients_emails
        context = {"job_application": self.job_application}
        subject = "apply/email/new_for_siae_subject.txt"
        body = "apply/email/new_for_siae_body.txt"
        return get_email_message(to, context, subject, body)

    @property
    def recipients_emails(self):
        return self.get_recipients().values_list("user__email", flat=True)


class NewQualifiedJobAppEmployersNotification(NotificationBase):
    """
    Subscribe a recipient to job descriptions or send notifications.
    A job description represents an SiaeJobDescription object also known as
      a `job_application.selected_jobs` relation.

    ----

    Usage:
    ## Send a notification from a job_application which have selected_jobs
    ```
    notification = cls(job_application=job_application)
    notification.send()
    ```

    ## Opt in or opt out a recipient to a list of job descriptions
    ```
    selected_jobs_pks = [JobDescription.objects.get()]
    cls.subscribe(recipient=recipient, subscribed_pks=selected_jobs_pks)

    # unsubscribe the same way:
    cls.unsubscribe(recipient=recipient, subscribed_pks=selected_jobs_pks)
    ```

    ## Know if a recipient opted out to a specific job description notifications
    ```
    job_description = JobDescription.objects.get()
    cls.is_subscribed(recipient=recipient, subscribed_pk=job_description.pk)
    ```
    """

    NAME = "new_qualified_job_application_employers_email"
    SUB_NAME = "subscribed_job_descriptions"

    def __init__(self, job_application):
        self.job_application = job_application
        self.subscribed_pks = self.job_application.selected_jobs.values_list("pk", flat=True)
        active_memberships = job_application.to_siae.siaemembership_set.active()
        super().__init__(recipients_qs=active_memberships)

    def get_recipients(self):
        return super().get_recipients()

    @property
    def email(self):
        to = self.recipients_emails
        context = {"job_application": self.job_application}
        subject = "apply/email/new_for_siae_subject.txt"
        body = "apply/email/new_for_siae_body.txt"
        return get_email_message(to, context, subject, body)

    @property
    def recipients_emails(self):
        return self.get_recipients().values_list("user__email", flat=True)

    @property
    def subscribed_lookup(self):
        dicts = [{f"notifications__{self.NAME}__{self.SUB_NAME}__contains": pk} for pk in self.subscribed_pks]

        q_sub_query = Q()
        for query in dicts:
            q_sub_query |= Q(**query)

        if self.SEND_TO_UNSET_RECIPIENTS:
            q_sub_query |= self.unset_lookup

        return q_sub_query

    @classmethod
    def is_subscribed(cls, recipient, subscribed_pk):
        if cls.SEND_TO_UNSET_RECIPIENTS and not recipient.notifications.get(cls.NAME):
            return True
        return subscribed_pk in cls._get_recipient_subscribed_pks(recipient)

    @classmethod
    def recipient_subscribed_pks(cls, recipient, default_pks=None):
        if cls.SEND_TO_UNSET_RECIPIENTS and not recipient.notifications.get(cls.NAME):
            return list(default_pks)
        return list(cls._get_recipient_subscribed_pks(recipient))

    @classmethod
    def subscribe(cls, recipient, subscribed_pks, save=True):
        pks_set = cls._get_recipient_subscribed_pks(recipient)
        pks_set.update(subscribed_pks)
        recipient.notifications[cls.NAME][cls.SUB_NAME] = list(pks_set)
        if save:
            recipient.save()
        return recipient

    @classmethod
    def unsubscribe(cls, recipient, subscribed_pks):
        pks_set = cls._get_recipient_subscribed_pks(recipient)
        pks_set.difference_update(subscribed_pks)
        recipient.notifications[cls.NAME][cls.SUB_NAME] = list(pks_set)
        recipient.save()

    @classmethod
    def subscribe_hard(cls, recipient, subscribed_pks):
        cls._get_recipient_subscribed_pks(recipient)
        recipient.notifications[cls.NAME][cls.SUB_NAME] = list(subscribed_pks)
        recipient.save()

    @classmethod
    def _get_recipient_subscribed_pks(cls, recipient):
        """
        Returns job descriptions' pk a recipient subscribed to.
        To make sure pk are unique, we use a `set` data type.
        => return set(pks)
        """
        subscribed_pks = recipient.notifications.setdefault(cls.NAME, {}).setdefault(cls.SUB_NAME, set())
        return set(subscribed_pks)
