from django.core import mail
from django.test import TestCase

from itou.job_applications.factories import JobApplicationFactory
from itou.job_applications.notifications import NewSpontaneousJobAppEmployersNotification
from itou.siaes.factories import SiaeWith4MembershipsFactory


BaseNotification = NewSpontaneousJobAppEmployersNotification


class NotificationsBaseClassTest(TestCase):
    # Use a child class to test parent class. Maybe refactor that later.

    def setUp(self):
        self.siae = SiaeWith4MembershipsFactory()
        self.job_application = JobApplicationFactory(to_siae=self.siae)
        self.notification = BaseNotification(job_application=self.job_application)

        # Make sure notifications are empty
        self.siaemembership_set = self.siae.siaemembership_set
        self.membership = self.siaemembership_set.filter(user__is_active=True).first()
        self.assertFalse(self.membership.notifications)

    def test_subscribe(self):
        BaseNotification.subscribe(recipient=self.membership)
        self.assertTrue(self.membership.notifications)  # Dict is not empty
        self.assertTrue(BaseNotification.is_subscribed(recipient=self.membership))

        key = self.notification.NAME
        self.assertTrue(self.membership.notifications.get(key))  # Key exists

    def test_unsubscribe(self):
        self.notification.unsubscribe(recipient=self.membership)
        self.assertTrue(self.membership.notifications)  # Dict is not empty
        self.assertFalse(BaseNotification.is_subscribed(recipient=self.membership))

        key = self.notification.NAME
        self.assertTrue(self.membership.notifications.get(key))  # Key exists

    def test_unsubscribe_and_subscribe(self):
        """
        Make sure it's possible to toggle preferences.
        """
        BaseNotification.unsubscribe(recipient=self.membership)
        self.assertFalse(BaseNotification.is_subscribed(recipient=self.membership))

        BaseNotification.subscribe(recipient=self.membership)
        self.assertTrue(BaseNotification.is_subscribed(recipient=self.membership))

        BaseNotification.unsubscribe(recipient=self.membership)
        self.assertFalse(BaseNotification.is_subscribed(recipient=self.membership))

    def test_recipients_email(self):
        recipients_emails = self.notification.recipients_emails
        self.assertEqual(
            self.siaemembership_set.filter(user__email__in=recipients_emails).count(), len(recipients_emails)
        )

    def test_desactivate_user_not_in_recipients_email(self):
        recipients_emails = self.notification.recipients_emails
        self.assertEqual(
            self.siaemembership_set.filter(user__is_active=False, user__email__in=recipients_emails).count(), 0
        )

    def test_get_recipients_default_send_to_unset_recipients(self):
        # Unset recipients are present in get_recipients if SEND_TO_UNSET_RECIPIENTS = True
        recipients = self.notification.get_recipients()
        self.assertEqual(self.siaemembership_set.filter(user__is_active=True).count(), len(recipients))

    def test_get_recipients_default_dont_send_to_unset_recipients(self):
        # Unset recipients are not present in get_recipients if SEND_TO_UNSET_RECIPIENTS = False
        self.notification.SEND_TO_UNSET_RECIPIENTS = False
        recipients = self.notification.get_recipients()
        self.assertEqual(len(recipients), 0)

    def test_send(self):
        self.notification.send()

        receivers = [receiver for message in mail.outbox for receiver in message.to]
        self.assertEqual(self.notification.email.to, receivers)
