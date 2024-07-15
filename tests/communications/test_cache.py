from datetime import date, timedelta

import pytest
from django.core.cache import cache
from freezegun import freeze_time
from pytest_django.asserts import assertNumQueries

from itou.communications.cache import CACHE_ACTIVE_ANNOUNCEMENTS_KEY
from itou.utils.context_processors import active_announcement_campaign
from tests.communications.factories import AnnouncementCampaignFactory, AnnouncementItemFactory
from tests.utils.test import TestCase


class AnnouncementCampaignCacheTest(TestCase):
    @pytest.fixture(autouse=True)
    def empty_announcements_cache(self, empty_active_announcements_cache):
        pass

    def test_active_announcement_campaign_context_processor_cached(self):
        campaign = AnnouncementCampaignFactory(with_item=True, start_date=date.today().replace(day=1), live=True)

        with assertNumQueries(0):
            active_announcement_campaign(None)["active_campaign_announce"] == campaign

        # test cached value is kept up-to-date
        campaign.max_items += 1
        campaign.save()

        with assertNumQueries(0):
            assert active_announcement_campaign(None)["active_campaign_announce"].max_items == campaign.max_items

        item = AnnouncementItemFactory(campaign=campaign)
        with assertNumQueries(0):
            assert active_announcement_campaign(None)["active_campaign_announce"].items.count() == 2

        item.delete()
        with assertNumQueries(0):
            assert active_announcement_campaign(None)["active_campaign_announce"].items.count() == 1

        # test cache does not become invalidated when saving a new campaign
        new_campaign = AnnouncementCampaignFactory(
            with_item=True, start_date=(campaign.start_date + timedelta(days=40)).replace(day=1)
        )
        with assertNumQueries(0):
            active_announcement_campaign(None)["active_campaign_announce"] == campaign

        # test cached value is removed with the campaign
        campaign.delete()
        new_campaign.delete()
        with assertNumQueries(0):
            active_announcement_campaign(None)["active_campaign_announce"] is None

    def test_costless_announcement_campaign_cache_when_no_announcement_created(self):
        cache_updated_query_cost = 1

        with assertNumQueries(cache_updated_query_cost):
            assert active_announcement_campaign(None)["active_campaign_announce"] is None

        with assertNumQueries(0):
            assert active_announcement_campaign(None)["active_campaign_announce"] is None

    @freeze_time("2024-01-30")
    def test_active_announcement_campaign_cache_timeout(self):
        campaign = AnnouncementCampaignFactory(start_date=date(2024, 1, 1), with_item=True)

        with assertNumQueries(0):
            assert active_announcement_campaign(None)["active_campaign_announce"] == campaign

        # NOTE: this test requires that the cache client is Redis (for the ttl function)
        cache_time_remaining = cache.ttl(CACHE_ACTIVE_ANNOUNCEMENTS_KEY)
        twenty_four_hours = 60 * 60 * 24
        assert cache_time_remaining == twenty_four_hours
