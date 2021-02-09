from django.db.models import Q

from itou.utils.emails import get_email_message
from itou.utils.notifications.base_class import NotificationBase


class NewSpontaneousJobAppSiaeNotification(NotificationBase):
    NAME = "new_spontaneous_job_application_siae_email"

    def __init__(self, job_application=None):
        active_memberships = None
        if job_application:
            active_memberships = job_application.to_siae.siaemembership_set.active()
        super().__init__(recipients_qs=active_memberships)
        self.job_application = job_application

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


class NewQualifiedJobAppSiaeNotification(NotificationBase):
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

    NAME = "new_qualified_job_application_siae_email"
    SUB_NAME = "subscribed_job_descriptions"

    def __init__(self, job_application):
        self.job_application = job_application
        self.subscribed_pks = self.job_application.selected_jobs.values_list("pk", flat=True)
        active_memberships = job_application.to_siae.siaemembership_set.active()
        super().__init__(recipients_qs=active_memberships)

    def get_recipients(self):
        return super().get_recipients(subscribed_pks=self.subscribed_pks)

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

        return q_sub_query

    @staticmethod
    def is_subscribed(recipient, subscribed_pk):
        return subscribed_pk in NewQualifiedJobAppSiaeNotification._get_recipient_subscribed_pks(recipient)

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
    def _get_recipient_subscribed_pks(cls, recipient):
        """
        Returns job descriptions' pk a recipient subscribed to.
        To make sure pk are unique, we use a `set` data type.
        => return set(pks)
        """
        subscribed_pks = recipient.notifications.setdefault(cls.NAME, {}).setdefault(cls.SUB_NAME, set())
        return set(subscribed_pks)
