import six
from django.conf import settings
from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.translation import gettext as _
from herald import registry
from herald.base import EmailNotification
from herald.models import UserNotification


# Disable a notification kind for a user:
# 1/ Create a new entry in UserNotification:
# user_notif_preferences = UserNotification(user=member)
# It means the user has custom notifications preferences.

# 2/ Mark a notification kind as disabled for a user, ie add a new relation between UserNotification and Notification.
# notification_kind = Notification.objects.get(notification_class=SiaeNewJobApplicationEmail.get_class_path())
# user_notif_preferences.disabled_notifications.add(notification_kind)


@registry.register_decorator()
class SiaeNewJobApplicationEmail(EmailNotification):
    template_name = "siae_new_job_application"  # see templates/notifications
    sent_from = settings.DEFAULT_FROM_EMAIL

    @classmethod
    def resend(cls, sent_notification, raise_exception=False):
        """
        Takes a saved sent_notification and sends it again.
        returns boolean whether or not the notification was sent successfully
        """

        # handle skipping a notification based on user preference
        recipients = sent_notification.get_recipients()  # aka self.to_emails
        notification_class = sent_notification.__class__.get_class_path()
        unsubscribed_members = UserNotification.objects.filter(
            user__email__in=recipients, disabled_notifications__notification_class=notification_class
        ).values_list("user__email", flat=True)

        recipients = [recipient for recipient in recipients if recipient not in unsubscribed_members]

        try:
            cls._send(
                sent_notification.get_recipients(),
                sent_notification.text_content,
                sent_notification.html_content,
                sent_notification.sent_from,
                sent_notification.subject,
                sent_notification.get_extra_data(),
                sent_notification.get_attachments(),
            )
            sent_notification.status = sent_notification.STATUS_SUCCESS
        except Exception as exc:  # pylint: disable=W0703
            sent_notification.status = sent_notification.STATUS_FAILED
            sent_notification.error_message = str(exc)

            if raise_exception:
                raise exc

        sent_notification.date_sent = timezone.now()
        sent_notification.save()

        cls._delete_expired_notifications()

        return sent_notification.status == sent_notification.STATUS_SUCCESS

    @staticmethod
    def get_demo_args():
        return [get_user_model().objects.first()]

    def __init__(self, job_application, siae):
        self.context = {"job_application": job_application}
        self.to_emails = list(siae.members.filter(is_active=True).values_list("email", flat=True))

    def get_subject(self):
        return _(f"Nouvelle candidature")

    def render(self, render_type, context):
        """
        Renders the template
        :param render_type: the content type to render
        :param context: context data dictionary
        :return: the rendered content
        """
        content = render_to_string(
            "notifications/{}/{}.{}".format(
                render_type, self.template_name, "txt" if render_type == "text" else render_type
            ),
            context,
        )

        return content
