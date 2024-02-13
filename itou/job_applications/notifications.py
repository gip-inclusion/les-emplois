from django.db.models import Q

from itou.common_apps.notifications.base_class import BaseNotification
from itou.communications import NotificationCategory, registry as notifications_registry
from itou.communications.dispatch import (
    EmailNotification,
    EmployerNotification,
    JobSeekerNotification,
    PrescriberNotification,
    PrescriberOrEmployerNotification,
)
from itou.utils.emails import get_email_message


class NewSpontaneousJobAppEmployersNotification(BaseNotification):
    NAME = "new_spontaneous_job_application_employers_email"

    def __init__(self, job_application):
        self.job_application = job_application
        active_memberships = job_application.to_company.companymembership_set.active()
        super().__init__(recipients_qs=active_memberships)

    @property
    def email(self):
        to = self.recipients_emails
        context = {"job_application": self.job_application}
        subject = "apply/email/new_for_employer_subject.txt"
        body = "apply/email/new_for_employer_body.txt"
        return get_email_message(to, context, subject, body)

    @property
    def recipients_emails(self):
        return self.get_recipients().values_list("user__email", flat=True)


class NewQualifiedJobAppEmployersNotification(BaseNotification):
    """
    Job descriptions notifications: sending and subscription.
    A job description represents an JobDescription object also known as
      a `job_application.selected_jobs` relation.

    Notifications preferences are stored as a JSON dictionary like this one:
    ```
    {
        notification.name: {
            notification.sub_name: [3, 5, 10] # primary keys of objects a recipient subscribed to.
        }
    }
    ```

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
        active_memberships = job_application.to_company.companymembership_set.active()
        super().__init__(recipients_qs=active_memberships)

    @property
    def email(self):
        to = self.recipients_emails
        context = {"job_application": self.job_application}
        subject = "apply/email/new_for_employer_subject.txt"
        body = "apply/email/new_for_employer_body.txt"
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
        subscribed_pk = int(subscribed_pk)
        return subscribed_pk in cls._get_recipient_subscribed_pks(recipient)

    @classmethod
    def recipient_subscribed_pks(cls, recipient, default_pks=None):
        if cls.SEND_TO_UNSET_RECIPIENTS and not recipient.notifications.get(cls.NAME):
            return list(default_pks)
        return list(cls._get_recipient_subscribed_pks(recipient))

    @classmethod
    def subscribe(cls, recipient, subscribed_pks, save=True):
        subscribed_pks = [int(pk) for pk in subscribed_pks]  # make sure we store integers
        pks_set = cls._get_recipient_subscribed_pks(recipient)
        pks_set.update(subscribed_pks)
        cls.replace_subscriptions(recipient, subscribed_pks=pks_set)

    @classmethod
    def unsubscribe(cls, recipient, subscribed_pks):
        subscribed_pks = [int(pk) for pk in subscribed_pks]  # make sure we store integers
        pks_set = cls._get_recipient_subscribed_pks(recipient)
        pks_set.difference_update(subscribed_pks)
        cls.replace_subscriptions(recipient, subscribed_pks=pks_set)

    @classmethod
    def replace_subscriptions(cls, recipient, subscribed_pks):
        if not recipient.notifications.get(cls.NAME):
            cls._get_recipient_subscribed_pks(recipient)
        subscribed_pks = [int(pk) for pk in subscribed_pks]  # make sure we store integers
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


@notifications_registry.register
class JobApplicationNewForJobSeekerNotification(JobSeekerNotification, EmailNotification):
    """Notification sent to job seeker when created"""

    name = "Confirmation d’envoi de candidature"
    category = NotificationCategory.JOB_APPLICATION
    subject_template = "apply/email/new_for_job_seeker_subject.txt"
    body_template = "apply/email/new_for_job_seeker_body.txt"


@notifications_registry.register
class JobApplicationNewForPrescriberNotification(PrescriberNotification, EmailNotification):
    """Notification sent to prescriber when created"""

    name = "Confirmation d’envoi de candidature"
    category = NotificationCategory.JOB_APPLICATION
    subject_template = "apply/email/new_for_prescriber_subject.txt"
    body_template = "apply/email/new_for_prescriber_body.txt"


@notifications_registry.register
class JobApplicationNewForEmployerNotification(EmployerNotification, EmailNotification):
    """Notification sent to new employers when created"""

    name = "Nouvelle candidature"
    category = NotificationCategory.JOB_APPLICATION
    subject_template = "apply/email/new_for_employer_subject.txt"
    body_template = "apply/email/new_for_employer_body.txt"


@notifications_registry.register
class JobApplicationAcceptedForJobSeekerNotification(JobSeekerNotification, EmailNotification):
    """Notification sent to job seeker when accepted"""

    name = "Confirmation d’acceptation de candidature"
    category = NotificationCategory.JOB_APPLICATION
    subject_template = "apply/email/accept_for_job_seeker_subject.txt"
    body_template = "apply/email/accept_for_job_seeker_body.txt"


@notifications_registry.register
class JobApplicationAcceptedForPrescriberNotification(PrescriberNotification, EmailNotification):
    """Notification sent to prescriber when accepted"""

    name = "Confirmation d’acceptation de candidature"
    category = NotificationCategory.JOB_APPLICATION
    subject_template = "apply/email/accept_for_proxy_subject.txt"
    body_template = "apply/email/accept_for_proxy_body.txt"

    def get_context(self):
        context = super().get_context()
        if context["job_application"].sender_prescriber_organization:
            # Include the survey link for all prescribers's organizations.
            context["prescriber_survey_link"] = context[
                "job_application"
            ].sender_prescriber_organization.accept_survey_url
        return context


@notifications_registry.register
class JobApplicationRefusedForJobSeekerNotification(JobSeekerNotification, EmailNotification):
    """Notification sent to job seeker when transferred"""

    name = "Refus de candidature"
    category = NotificationCategory.JOB_APPLICATION
    subject_template = "apply/email/refuse_subject.txt"
    body_template = "apply/email/refuse_body_for_job_seeker.txt"


@notifications_registry.register
class JobApplicationRefusedForPrescriberNotification(PrescriberNotification, EmailNotification):
    """Notification sent to prescriber when refused"""

    name = "Refus de candidature"
    category = NotificationCategory.JOB_APPLICATION
    subject_template = "apply/email/refuse_subject.txt"
    body_template = "apply/email/refuse_body_for_proxy.txt"


@notifications_registry.register
class JobApplicationTransferredForJobSeekerNotification(JobSeekerNotification, EmailNotification):
    """Notification sent to job seeker when transferred"""

    name = "Transfert de candidature"
    category = NotificationCategory.JOB_APPLICATION
    subject_template = "apply/email/transfer_job_seeker_subject.txt"
    body_template = "apply/email/transfer_job_seeker_body.txt"


@notifications_registry.register
class JobApplicationTransferredForPrescriberNotification(PrescriberNotification, EmailNotification):
    """Notification sent to prescriber when transferred"""

    name = "Transfert de candidature"
    category = NotificationCategory.JOB_APPLICATION
    subject_template = "apply/email/transfer_prescriber_subject.txt"
    body_template = "apply/email/transfer_prescriber_body.txt"


@notifications_registry.register
class JobApplicationTransferredForEmployerNotification(EmployerNotification, EmailNotification):
    """Notification sent to original employer when transferred"""

    name = "Transfert de candidature"
    category = NotificationCategory.JOB_APPLICATION
    subject_template = "apply/email/transfer_source_employer_subject.txt"
    body_template = "apply/email/transfer_source_employer_body.txt"


@notifications_registry.register
class JobApplicationCanceledNotification(PrescriberOrEmployerNotification, EmailNotification):
    name = "Embauche annulée"
    category = NotificationCategory.JOB_APPLICATION
    subject_template = "apply/email/cancel_subject.txt"
    body_template = "apply/email/cancel_body.txt"
