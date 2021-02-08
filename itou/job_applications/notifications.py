from django.db.models import Q

from itou.utils.emails import get_email_message
from itou.utils.notifications.base_class import NotificationBase


class NewJobApplicationSiaeEmailNotification(NotificationBase):
    def __new__(cls, *args, **kwargs):
        job_application = kwargs.get("job_application")
        if not job_application:
            raise ValueError

        obj = super(NewJobApplicationSiaeEmailNotification, cls).__new__(
            NewQualifiedJobApplicationSiaeEmailNotification
        )

        if job_application.is_spontaneous:
            obj = super(NewJobApplicationSiaeEmailNotification, cls).__new__(
                NewSpontaneousJobApplicationSiaeEmailNotification
            )

        obj.__init__(*args, **kwargs)
        return obj


class NewSpontaneousJobApplicationSiaeEmailNotification(NotificationBase):
    def __init__(self, job_application=None):
        active_memberships = None
        if job_application:
            active_memberships = job_application.to_siae.siaemembership_set.active()
        super().__init__(recipients_qs=active_memberships)
        self.job_application = job_application

    @property
    def name(self):
        return "new_spontaneous_job_application_siae_email"

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


class NewQualifiedJobApplicationSiaeEmailNotification(NotificationBase):
    """
    Subscribe a recipient to a job description and send notifications.
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
    selected_jobs_pks = JobDescription.objects.filter().values_list("pk", flat=True)
    notification = cls(selected_jobs_pks=selected_jobs_pks)
    notification.subscribe(recipient)

    # unsubscribe the same way:
    notification.unsubscribe(recipient)
    ```

    ## Know if a recipient opted out to a specific job description notifications
    ```
    selected_jobs_pks = [JobDescription.objects.get()]
    notification = cls(selected_jobs_pks=selected_jobs_pks)
    notification.is_subscribed(recipient)
    ```
    """

    def __init__(self, selected_jobs_pks=None, job_application=None):
        """
        Arguments:
        - selected_jobs_pk: list of integers. It represents an SiaeJobDescription object
        (also known as a job_application.selected_jobs relation). If empty, job_application is mandatory.
        - job_application: a JobApplication object. If empty, selected_jobs_pks is mandatory.
        """
        active_memberships = None
        self.job_application = job_application
        self.subscribed_pks = selected_jobs_pks
        if job_application:
            active_memberships = job_application.to_siae.siaemembership_set.active()
            self.subscribed_pks = job_application.selected_jobs.values_list("pk", flat=True)
        if not selected_jobs_pks and not job_application:
            raise ValueError
        super().__init__(recipients_qs=active_memberships)

    @property
    def email(self):
        to = self.recipients_emails
        context = {"job_application": self.job_application}
        subject = "apply/email/new_for_siae_subject.txt"
        body = "apply/email/new_for_siae_body.txt"
        return get_email_message(to, context, subject, body)

    @property
    def name(self):
        return "new_qualified_job_application_siae_email"

    @property
    def sub_name(self):
        return "subscribed_job_descriptions"

    @property
    def recipients_emails(self):
        return self.get_recipients().values_list("user__email", flat=True)

    @property
    def subscribed_lookup(self):
        dicts = [{f"notifications__{self.name}__{self.sub_name}__contains": pk} for pk in self.subscribed_pks]

        q_sub_query = Q()
        for query in dicts:
            q_sub_query |= Q(**query)

        return q_sub_query

    def is_subscribed(self, recipient):
        """
        Return a boolean to know if a recipient has subscribed to a job description notification.
        Quite logically, only one job description is possible.
        Usage :
        ```
        notification = cls(selected_jobs_pk=[2])
        notification.is_subscribed(my_recipient)
        ```
        """
        if len(self.subscribed_pks) > 1:
            return AttributeError
        return self.subscribed_pks[0] in self._get_recipient_subscribed_pks(recipient)

    def subscribe(self, recipient, save=True):
        pks_set = self._get_recipient_subscribed_pks(recipient)
        pks_set.update(self.subscribed_pks)
        recipient.notifications[self.name][self.sub_name] = list(pks_set)
        if save:
            recipient.save()
        return recipient

    def unsubscribe(self, recipient):
        pks_set = self._get_recipient_subscribed_pks(recipient)
        pks_set.difference_update(self.subscribed_pks)
        recipient.notifications[self.name][self.sub_name] = list(pks_set)
        recipient.save()

    def _get_recipient_subscribed_pks(self, recipient):
        """
        Returns job descriptions' pk a recipient subscribed to.
        To make sure pk are unique, we use a `set` data type.
        => return set(pks)
        """
        subscribed_pks = recipient.notifications.setdefault(self.name, {}).setdefault(self.sub_name, set())
        return set(subscribed_pks)
