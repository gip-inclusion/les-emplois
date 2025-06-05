from datetime import date, timedelta
from unittest import mock

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.cache import caches
from django.test import RequestFactory
from django.urls import reverse
from freezegun import freeze_time
from pytest_django.asserts import assertNumQueries

from itou.communications.cache import CACHE_ACTIVE_ANNOUNCEMENTS_KEY
from itou.utils.context_processors import active_announcement_campaign
from tests.communications.factories import AnnouncementCampaignFactory, AnnouncementItemFactory
from tests.users.factories import JobSeekerFactory


class TestAnnouncementCampaignCache:
    @pytest.fixture(autouse=True)
    def empty_announcements_cache(self, empty_active_announcements_cache):
        pass

    def test_active_announcement_campaign_context_processor_cached(self):
        campaign = AnnouncementCampaignFactory(with_item=True, start_date=date.today().replace(day=1), live=True)
        request = RequestFactory()
        request.user = AnonymousUser()

        with assertNumQueries(0):
            active_announcement_campaign(request)["active_campaign_announce"] == campaign

        # test cached value is kept up-to-date
        campaign.max_items += 1
        campaign.save()

        with assertNumQueries(0):
            assert active_announcement_campaign(request)["active_campaign_announce"].max_items == campaign.max_items

        item = AnnouncementItemFactory(campaign=campaign)
        with assertNumQueries(0):
            assert active_announcement_campaign(request)["active_campaign_announce"].items.count() == 2

        item.delete()
        with assertNumQueries(0):
            assert active_announcement_campaign(request)["active_campaign_announce"].items.count() == 1

        # test cache does not become invalidated when saving a new campaign
        new_campaign = AnnouncementCampaignFactory(
            with_item=True, start_date=(campaign.start_date + timedelta(days=40)).replace(day=1)
        )
        with assertNumQueries(0):
            active_announcement_campaign(request)["active_campaign_announce"] == campaign

        # test cached value is removed with the campaign
        campaign.delete()
        new_campaign.delete()
        with assertNumQueries(0):
            active_announcement_campaign(request)["active_campaign_announce"] is None

    def test_costless_announcement_campaign_cache_when_no_announcement_created(self):
        request = RequestFactory()
        request.user = AnonymousUser()
        cache_updated_query_cost = 1

        with assertNumQueries(cache_updated_query_cost):
            assert active_announcement_campaign(request)["active_campaign_announce"] is None

        with assertNumQueries(0):
            assert active_announcement_campaign(request)["active_campaign_announce"] is None

    @freeze_time("2024-01-31")
    def test_active_announcement_campaign_cache_timeout(self):
        campaign = AnnouncementCampaignFactory(start_date=date(2024, 1, 1), with_item=True)
        request = RequestFactory()
        request.user = AnonymousUser()

        with assertNumQueries(0):
            assert active_announcement_campaign(request)["active_campaign_announce"] == campaign

        # NOTE: this test requires that the cache client is Redis (for the ttl function)
        cache_time_remaining = caches["failsafe"].ttl(CACHE_ACTIVE_ANNOUNCEMENTS_KEY)
        twenty_four_hours = 60 * 60 * 24
        assert cache_time_remaining == twenty_four_hours

    @freeze_time("2024-01-31")
    def test_cache_failsafe(self, client, failing_cache):
        with mock.patch("itou.utils.cache.capture_exception") as sentry_mock:
            # Cache connection fails.
            caches["failsafe"] = failing_cache

            # Creating campaign will try to update the cache, shouldn't crash.
            campaign = AnnouncementCampaignFactory(start_date=date(2024, 1, 1), with_item=True)
            sentry_mock.assert_called()
            sentry_mock.reset_mock()

            # Page should not crash.
            client.force_login(JobSeekerFactory(with_address=True))
            response = client.get(reverse("dashboard:index"))
            assert response.status_code == 200
            sentry_mock.assert_called()
            sentry_mock.reset_mock()

            # Active campaign should be available in context.
            assert response.context["active_campaign_announce"] == campaign

            # Deleting campaign will try to update the cache, shouldn't crash.
            campaign.delete()
            sentry_mock.assert_called()
