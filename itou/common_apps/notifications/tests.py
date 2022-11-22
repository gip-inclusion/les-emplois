from django.core import mail

from itou.job_applications.factories import JobApplicationFactory
from itou.job_applications.notifications import NewSpontaneousJobAppEmployersNotification
from itou.siaes.factories import SiaeFactory, SiaeMembershipFactory
from itou.utils.test import TestCase


class NotificationsBaseClassTest(TestCase):
    # Use a child class to test parent class. Maybe refactor that later.

    def setUp(self):
        self.siae = SiaeFactory(with_membership=True)
        self.job_application = JobApplicationFactory(to_siae=self.siae)
        self.notification = NewSpontaneousJobAppEmployersNotification(job_application=self.job_application)

        # Make sure notifications are empty
        self.siaemembership_set = self.siae.siaemembership_set
        self.membership = self.siaemembership_set.first()
        self.assertFalse(self.membership.notifications)

    def test_subscribe(self):
        NewSpontaneousJobAppEmployersNotification.subscribe(recipient=self.membership)
        self.assertTrue(self.membership.notifications)  # Dict is not empty
        self.assertTrue(NewSpontaneousJobAppEmployersNotification.is_subscribed(recipient=self.membership))

        key = self.notification.NAME
        self.assertTrue(self.membership.notifications.get(key))  # Key exists

    def test_unsubscribe(self):
        self.notification.unsubscribe(recipient=self.membership)
        self.assertTrue(self.membership.notifications)  # Dict is not empty
        self.assertFalse(NewSpontaneousJobAppEmployersNotification.is_subscribed(recipient=self.membership))

        key = self.notification.NAME
        self.assertTrue(self.membership.notifications.get(key))  # Key exists

    def test_unsubscribe_and_subscribe(self):
        """
        Make sure it's possible to toggle preferences.
        """
        NewSpontaneousJobAppEmployersNotification.unsubscribe(recipient=self.membership)
        self.assertFalse(NewSpontaneousJobAppEmployersNotification.is_subscribed(recipient=self.membership))

        NewSpontaneousJobAppEmployersNotification.subscribe(recipient=self.membership)
        self.assertTrue(NewSpontaneousJobAppEmployersNotification.is_subscribed(recipient=self.membership))

        NewSpontaneousJobAppEmployersNotification.unsubscribe(recipient=self.membership)
        self.assertFalse(NewSpontaneousJobAppEmployersNotification.is_subscribed(recipient=self.membership))

    def test_recipients_email(self):
        recipients_emails = self.notification.recipients_emails
        self.assertEqual(
            self.siaemembership_set.filter(user__email__in=recipients_emails).count(), len(recipients_emails)
        )

    def test_inactive_user_not_in_recipients(self):
        SiaeMembershipFactory(siae=self.siae, user__is_active=False, is_admin=False)
        self.assertEqual(self.siaemembership_set.count(), 2)

        recipients = self.notification.get_recipients()
        self.assertEqual(len(recipients), 1)

    def test_get_recipients_default_send_to_unset_recipients(self):
        # Unset recipients are present in get_recipients if SEND_TO_UNSET_RECIPIENTS = True
        SiaeMembershipFactory(siae=self.siae, user__is_active=False, is_admin=False)
        recipients = self.notification.get_recipients()

        self.assertEqual(self.siaemembership_set.count(), 2)
        self.assertEqual(len(recipients), 1)

    def test_get_recipients_default_dont_send_to_unset_recipients(self):
        # Unset recipients are not present in get_recipients if SEND_TO_UNSET_RECIPIENTS = False
        self.notification.SEND_TO_UNSET_RECIPIENTS = False
        recipients = self.notification.get_recipients()
        self.assertEqual(len(recipients), 0)

    def test_send(self):
        self.notification.send()

        receivers = [receiver for message in mail.outbox for receiver in message.to]
        self.assertEqual(self.notification.email.to, receivers)


class NewSpontaneousJobAppEmployersNotificationTest(TestCase):
    def test_mail_content_when_subject_to_eligibility_rules(self):
        siae = SiaeFactory(subject_to_eligibility=True, with_membership=True)
        notification = NewSpontaneousJobAppEmployersNotification(
            job_application=JobApplicationFactory(to_siae=siae),
        )

        self.assertIn("PASS IAE", notification.email.body)

    def test_mail_content_when_not_subject_to_eligibility_rules(self):
        siae = SiaeFactory(not_subject_to_eligibility=True, with_membership=True)
        notification = NewSpontaneousJobAppEmployersNotification(
            job_application=JobApplicationFactory(to_siae=siae),
        )

        self.assertNotIn("PASS IAE", notification.email.body)
