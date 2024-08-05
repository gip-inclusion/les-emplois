from django.core.cache import cache
from django.urls import reverse

from itou.communications.cache import CACHE_ACTIVE_ANNOUNCEMENTS_KEY
from itou.users.enums import UserKind

from tests.communications.factories import AnnouncementCampaignFactory, AnnouncementItemFactory
from tests.users.factories import PrescriberFactory, JobSeekerFactory
from tests.utils.test import parse_response_to_soup


class TestNewsRender:
    def test_campaign_rendered_dashboard_prescripteur(self, client, snapshot):
        cache.delete(CACHE_ACTIVE_ANNOUNCEMENTS_KEY)
        campaign = AnnouncementCampaignFactory(for_snapshot=True)

        user = PrescriberFactory()
        client.force_login(user)
        response = client.get(reverse("news:home"))

        assert response.status_code == 200
        assert response.context["news"][0].items.count() == campaign.items.count()

        assert len(response.context["news"][0].items_for_template()) <= campaign.max_items

        content = parse_response_to_soup(response, "#news")
        assert str(content) == snapshot

    def test_campaign_rendered_for_job_seeker(self, client, snapshot):
        cache.delete(CACHE_ACTIVE_ANNOUNCEMENTS_KEY)
        campaign = AnnouncementCampaignFactory(for_snapshot=True)
        assert campaign.items.exclude(user_kind_tags__contains=[UserKind.JOB_SEEKER]).exists()

        client.force_login(JobSeekerFactory())
        response = client.get(reverse("news:home"))

        assert response.status_code == 200

        # test that only candidate news items are rendered in the context
        items = response.context["news"][0].items
        for tags in items.values_list("user_kind_tags", flat=True):
            assert len(tags) == 0 or UserKind.JOB_SEEKER.value in tags
        assert items.count() < campaign.items.count()

        content = parse_response_to_soup(response, "#news")
        assert str(content) == snapshot
