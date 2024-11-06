from datetime import date

import pytest
from django.db import IntegrityError

from itou.communications import registry as notifications_registry
from itou.communications.apps import sync_notifications
from itou.communications.dispatch.base import BaseNotification
from itou.communications.models import NotificationRecord, NotificationSettings
from tests.communications.factories import AnnouncementCampaignFactory
from tests.companies.factories import CompanyMembershipFactory
from tests.users.factories import EmployerFactory, JobSeekerFactory, PrescriberFactory


class TestNotificationModel:
    @pytest.fixture
    def first_notification(self):
        @notifications_registry.register
        class FirstNotification(BaseNotification):
            name = "First"
            category = "First"

        yield
        notifications_registry.unregister(FirstNotification)

    @pytest.fixture
    def second_notification(self):
        @notifications_registry.register
        class SecondNotification(BaseNotification):
            name = "Second"
            category = "Second"

        yield
        notifications_registry.unregister(SecondNotification)

    def test_managers(self, first_notification, second_notification):
        sync_notifications(NotificationRecord)
        assert NotificationRecord.objects.filter(category__in=["First", "Second"]).count() == 2
        assert NotificationRecord.include_obsolete.filter(category__in=["First", "Second"]).count() == 2

        # Set second notification obsolete, should not be listed by default
        NotificationRecord.objects.filter(category="Second").update(is_obsolete=True)
        assert NotificationRecord.objects.filter(category__in=["First", "Second"]).count() == 1
        assert NotificationRecord.include_obsolete.filter(category__in=["First", "Second"]).count() == 2

    def test_str(self, first_notification, second_notification):
        sync_notifications(NotificationRecord)
        notifications = NotificationRecord.objects.filter(category__in=["First", "Second"])
        assert str(notifications[0]) == "First"
        assert str(notifications[1]) == "Second"


class TestNotificationSettingsModel:
    def setup_method(self):
        self.job_seeker = JobSeekerFactory(first_name="John", last_name="Doe", with_disabled_notifications=True)
        self.employer = EmployerFactory(
            first_name="Alice", last_name="Doe", with_company=True, with_disabled_notifications=True
        )
        self.employer_structure = self.employer.company_set.first()
        self.prescriber = PrescriberFactory(
            first_name="Bob", last_name="Doe", membership=True, with_disabled_notifications=True
        )
        self.prescriber_structure = self.prescriber.prescriberorganization_set.first()

    def test_queryset(self):
        assert NotificationSettings.objects.count() == 3
        assert NotificationSettings.objects.for_structure(None).count() == 1
        assert NotificationSettings.objects.for_structure(self.employer_structure).count() == 1
        assert NotificationSettings.objects.for_structure(self.prescriber_structure).count() == 1

        # Create new membership related to employer / employer structure
        membership1 = CompanyMembershipFactory(user=self.employer)
        membership2 = CompanyMembershipFactory(company=self.employer_structure)

        # No changes by default (settings only created when calling NotificationSettings.get_or_create)
        assert NotificationSettings.objects.count() == 3
        assert NotificationSettings.objects.for_structure(None).count() == 1
        assert NotificationSettings.objects.for_structure(self.employer_structure).count() == 1
        assert NotificationSettings.objects.for_structure(self.prescriber_structure).count() == 1

        # Fetch settings
        NotificationSettings.get_or_create(membership1.user, membership1.company)
        NotificationSettings.get_or_create(membership2.user, membership2.company)
        assert NotificationSettings.objects.count() == 5
        assert NotificationSettings.objects.for_structure(None).count() == 1
        assert NotificationSettings.objects.for_structure(self.employer_structure).count() == 2
        assert NotificationSettings.objects.for_structure(self.employer_structure).filter(user=self.employer).exists()
        assert (
            NotificationSettings.objects.for_structure(self.employer_structure).filter(user=membership2.user).exists()
        )
        assert NotificationSettings.objects.for_structure(self.prescriber_structure).count() == 1

    def test_str(self):
        assert str(NotificationSettings.get_or_create(self.job_seeker)[0]) == "Paramètres de notification de John DOE"
        assert (
            str(NotificationSettings.get_or_create(self.employer, self.employer_structure)[0])
            == f"Paramètres de notification de Alice DOE ({self.employer_structure})"
        )
        assert (
            str(NotificationSettings.get_or_create(self.prescriber, self.prescriber_structure)[0])
            == f"Paramètres de notification de Bob DOE ({self.prescriber_structure})"
        )


class TestAnnouncementCampaignModel:
    def test_end_date(self):
        campaign = AnnouncementCampaignFactory(start_date=date(2024, 1, 1))
        assert campaign.end_date == date(2024, 1, 31)

    def test_max_items_constraint_too_low(self):
        with pytest.raises(IntegrityError):
            AnnouncementCampaignFactory(max_items=0)

    def test_max_items_constraint_too_high(self):
        with pytest.raises(IntegrityError):
            AnnouncementCampaignFactory(max_items=11)

    def test_start_date_day_constraint(self):
        # must be on first day of month
        with pytest.raises(IntegrityError):
            AnnouncementCampaignFactory(start_date=date(2024, 1, 2))

    def test_start_date_conflict_constraint(self):
        # can modify existing value without triggering constraint
        existing_campaign = AnnouncementCampaignFactory(start_date=date(2024, 1, 1))
        existing_campaign.start_date = date(2024, 2, 1)
        existing_campaign.save()

        # cannot conflict existing date with a new instance
        with pytest.raises(IntegrityError):
            AnnouncementCampaignFactory(start_date=existing_campaign.start_date)
