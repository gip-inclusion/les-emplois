from django.core.cache import cache
from django.urls import reverse

from itou.communications.cache import CACHE_ACTIVE_ANNOUNCEMENTS_KEY

from tests.communications.factories import AnnouncementCampaignFactory, AnnouncementItemFactory
from tests.utils.test import parse_response_to_soup


class TestNewsRender:
    def test_campaign_rendered_dashboard(self, client, snapshot):
        cache.delete(CACHE_ACTIVE_ANNOUNCEMENTS_KEY)
        campaign = AnnouncementCampaignFactory(for_snapshot=True)
        for i in range(4):
            AnnouncementItemFactory(campaign=campaign, for_snapshot=True)

        response = client.get(reverse("news:home"))
        assert response.status_code == 200
        content = parse_response_to_soup(response)
        assert str(content) == snapshot
