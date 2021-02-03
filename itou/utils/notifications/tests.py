from django.core import mail
from django.test import TestCase

from itou.job_applications.factories import JobApplicationFactory
from itou.job_applications.notifications import (
    NewQualifiedJobApplicationSiaeEmailNotification,
    NewSpontaneousJobApplicationSiaeEmailNotification,
)
from itou.siaes.factories import SiaeWith2MembershipsFactory, SiaeWithMembershipAndJobsFactory
from itou.users.factories import SiaeStaffFactory


class NotificationsBaseClassTest(TestCase):
    # Use a child class to test parent class. Maybe refactor that later.

    def setUp(self):
        self.siae = SiaeWith2MembershipsFactory()
        self.job_application = JobApplicationFactory(to_siae=self.siae)
        self.notification = NewSpontaneousJobApplicationSiaeEmailNotification(job_application=self.job_application)

        # Make sure notifications are empty
        self.siaemembership_set = self.siae.siaemembership_set
        self.membership = self.siaemembership_set.first()
        self.assertFalse(self.membership.notifications)

    def test_subscribe(self):
        self.notification.subscribe(recipient=self.membership)
        self.assertTrue(self.membership.notifications)  # Dict is not empty
        self.assertTrue(self.notification.is_subscribed(recipient=self.membership))

        key = self.notification.name
        self.assertTrue(self.membership.notifications.get(key))  # Key exists

    def test_unsubscribe(self):
        self.notification.unsubscribe(recipient=self.membership)
        self.assertTrue(self.membership.notifications)  # Dict is not empty
        self.assertFalse(self.notification.is_subscribed(recipient=self.membership))

        key = self.notification.name
        self.assertTrue(self.membership.notifications.get(key))  # Key exists

    def test_unsubscribe_and_subscribe(self):
        """
        Make sure it's possible to toggle preferences.
        """
        self.notification.unsubscribe(recipient=self.membership)
        self.assertFalse(self.notification.is_subscribed(recipient=self.membership))

        self.notification.subscribe(recipient=self.membership)
        self.assertTrue(self.notification.is_subscribed(recipient=self.membership))

        self.notification.unsubscribe(recipient=self.membership)
        self.assertFalse(self.notification.is_subscribed(recipient=self.membership))

    def test_subscribe_bulk(self):
        self.notification.subscribe_bulk(recipients=self.siaemembership_set)

        for membership in self.siaemembership_set.all():
            self.assertTrue(self.notification.is_subscribed(recipient=membership))

    def test_subscribe_unset_recipients(self):
        """
        By default, notification preferences are not stored.
        We may want to retrieve unset members and subscribe them.
        """
        self.notification._subscribe_unset_recipients()

        for membership in self.siaemembership_set.all():
            self.assertTrue(self.notification.is_subscribed(recipient=membership))

    def test_recipients_email(self):
        recipients_emails = self.notification.recipients_emails
        self.assertEqual(
            self.siaemembership_set.filter(user__email__in=recipients_emails).count(), len(recipients_emails)
        )

    def test_get_recipients_default_send_to_unset_recipients(self):
        # Unset recipients are present in get_recipients if SEND_TO_UNSET_RECIPIENTS = True
        recipients = self.notification.get_recipients()
        self.assertEqual(self.siaemembership_set.count(), len(recipients))

    def test_get_recipients_default_dont_send_to_unset_recipients(self):
        # Unset recipients are not present in get_recipients if SEND_TO_UNSET_RECIPIENTS = False
        self.notification.SEND_TO_UNSET_RECIPIENTS = False
        recipients = self.notification.get_recipients()
        self.assertEqual(len(recipients), 0)

    def test_send(self):
        self.notification.send()

        receivers = [receiver for message in mail.outbox for receiver in message.to]
        self.assertEqual(self.notification.email.to, receivers)


class NewJobApplicationSiaeEmailNotificationTest(TestCase):

    # No selected jobs linked
    # Test subscribe, unsubscribe and subscribe.
    # def create_test_data(self, siae_factory_model):
    #     siae = siae_factory_model()
    #     job_descriptions = siae.job_description_through.all()
    #     job_application = JobApplicationFactory(to_siae=siae)
    #     if job_descriptions:
    #         for job in job_descriptions:
    #             job_application.selected_jobs.add(job)
    #         job_application.save()
    #     notification = NewJobApplicationSiaeEmailNotification(job_application=job_application)
    #     return notification, siae.siaemembership_set

    def subscribe_and_unsubscribe_test(self, notification, membership):
        """
        Make sure it's possible to toggle preferences.
        """
        notification.subscribe(recipient=membership)
        self.assertTrue(notification.is_subscribed(recipient=membership))

        notification.unsubscribe(recipient=membership)
        self.assertFalse(notification.is_subscribed(recipient=membership))

        notification.subscribe(recipient=membership)
        self.assertTrue(notification.is_subscribed(recipient=membership))

    # def test_no_selected_jobs(self):
    #     notification, siaemembership_set = self.create_test_data(siae_factory_model=SiaeWith2MembershipsFactory)
    #     membership = siaemembership_set.first()
    #     self.assertFalse(membership.notifications)
    #     self.subscribe_and_unsubscribe_test(notification, membership)

    #     notification.unsubscribe(recipient=membership)

    #     self.assertEqual(len(notification.recipients_emails), siaemembership_set.count() - 1)

    def test_one_selected_job(self):
        siae = SiaeWithMembershipAndJobsFactory(romes=["N1101", "N1105", "N1103", "N4105", "N4104"])
        job_application = JobApplicationFactory(to_siae=siae)
        # For safety. Remove later.
        self.assertEqual(siae.jobs.count(), 5)

        # Add a selected job description to the application
        job_descriptions = siae.job_description_through.all()
        selected_job = job_descriptions[0]
        job_application.selected_jobs.add(selected_job)
        job_application.save()

        notification = NewQualifiedJobApplicationSiaeEmailNotification(job_application=job_application)

        # Receiver did not set any preference. Send the notification as default.
        membership = siae.siaemembership_set.first()
        self.assertFalse(membership.notifications)
        self.subscribe_and_unsubscribe_test(notification, membership)

        # Receiver is now subscribed to one kind of notification
        self.assertEqual(len(membership.notifications[notification.name]["subscribed_job_descriptions"]), 1)

        # A job application is sent concerning another job_description.
        # He should then be subscribed to two different notifications.
        job_application = JobApplicationFactory(to_siae=siae)
        selected_job = job_descriptions[1]
        job_application.selected_jobs.add(selected_job)
        job_application.save()

        notification = NewQualifiedJobApplicationSiaeEmailNotification(job_application=job_application)
        self.subscribe_and_unsubscribe_test(notification, membership)

        self.assertEqual(len(membership.notifications[notification.name]["subscribed_job_descriptions"]), 2)
        self.assertEqual(len(membership.notifications), 1)

        recipients = notification.recipients_emails
        self.assertEqual(len(recipients), 1)

        user = SiaeStaffFactory(siae=siae)
        siae.members.add(user)
        membership = siae.siaemembership_set.get(user=user)
        notification = NewQualifiedJobApplicationSiaeEmailNotification(job_application=job_application)
        notification.subscribe(membership)

        recipients = notification.recipients_emails
        self.assertEqual(len(recipients), 2)

    def test_multiple_selected_jobs(self):
        siae = SiaeWithMembershipAndJobsFactory(romes=["N1101", "N1105", "N1103", "N4105", "N4104"])
        job_descriptions = siae.job_description_through.all()

        # Add a member
        user = SiaeStaffFactory(siae=siae)
        siae.members.add(user)

        membership = siae.siaemembership_set.first()
        another_membership = siae.siaemembership_set.last()

        # Two selected jobs. 2 Users subscribed to the same one. We should have two recipients.
        job_application = JobApplicationFactory(to_siae=siae)
        job_application.selected_jobs.add(job_descriptions[0])
        job_application.selected_jobs.add(job_descriptions[1])
        job_application.save()

        notification = NewQualifiedJobApplicationSiaeEmailNotification(job_application=job_application)
        # Only for test purposes
        notification.SEND_TO_UNSET_RECIPIENTS = False
        notification.subscribe(membership)
        notification.subscribe(another_membership)
        recipients = notification.recipients_emails
        self.assertEqual(len(recipients), 2)

        # Two selected jobs. Each user subscribed to one of them. We should have two recipients.
        job_application = JobApplicationFactory(to_siae=siae)
        job_application.selected_jobs.add(job_descriptions[2])
        job_application.selected_jobs.add(job_descriptions[3])
        job_application.save()

        user = SiaeStaffFactory(siae=siae)
        siae.members.add(user)
        membership = siae.siaemembership_set.get(user=user)
        notification = NewQualifiedJobApplicationSiaeEmailNotification(selected_jobs_pks=[job_descriptions[2].pk])
        # Only for test purposes
        notification.SEND_TO_UNSET_RECIPIENTS = False
        notification.subscribe(membership)

        user = SiaeStaffFactory(siae=siae)
        siae.members.add(user)
        membership = siae.siaemembership_set.get(user=user)
        notification = NewQualifiedJobApplicationSiaeEmailNotification(selected_jobs_pks=[job_descriptions[3].pk])
        # Only for test purposes
        notification.SEND_TO_UNSET_RECIPIENTS = False
        notification.subscribe(membership)

        notification = NewQualifiedJobApplicationSiaeEmailNotification(job_application=job_application)
        notification.SEND_TO_UNSET_RECIPIENTS = False
        recipients = notification.recipients_emails
        self.assertEqual(len(recipients), 2)

    def test_spontaneous_applications(self):
        siae = SiaeWithMembershipAndJobsFactory(romes=["N1101", "N1105", "N1103", "N4105", "N4104"])
        job_descriptions = siae.job_description_through.all()

        # Add a member
        user = SiaeStaffFactory(siae=siae)
        siae.members.add(user)

        membership = siae.siaemembership_set.first()
        another_membership = siae.siaemembership_set.last()

        job_application = JobApplicationFactory(to_siae=siae)

        notification = NewSpontaneousJobApplicationSiaeEmailNotification(job_application=job_application)

        # Every SIAE members should receive it as they are subscribed by default.
        self.assertEqual(len(notification.recipients_emails), siae.members.count())
