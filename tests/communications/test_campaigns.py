from datetime import timedelta

from django.core.cache import cache
from django.forms.models import model_to_dict
from django.urls import reverse

from itou.communications.admin_forms import AnnouncementCampaignAdminForm
from itou.communications.cache import CACHE_ACTIVE_ANNOUNCEMENT_CAMPAIGN_KEY
from tests.communications.factories import AnnouncementCampaignFactory, AnnouncementItemFactory
from tests.utils.test import TestCase, parse_response_to_soup


class AnnouncementCampaignAdminFormTest(TestCase):
    def test_valid_campaign(self):
        expected_form_fields = ["max_items", "start_date", "end_date"]
        assert list(AnnouncementCampaignAdminForm().fields.keys()) == expected_form_fields

        form = AnnouncementCampaignAdminForm(model_to_dict(AnnouncementCampaignFactory.build()))
        assert form.is_valid()

    def test_invalid_campaign_date_range(self):
        campaign = AnnouncementCampaignFactory.build()
        campaign.end_date = campaign.start_date - timedelta(days=1)

        form = AnnouncementCampaignAdminForm(model_to_dict(campaign))

        expected_form_errors = ["Impossible de finir la campagne avant qu'elle ne commence."]
        assert form.errors["__all__"] == expected_form_errors

    def test_campaign_date_range_conflict(self):
        existing_campaign = AnnouncementCampaignFactory()
        campaign = AnnouncementCampaignFactory.build(
            start_date=existing_campaign.start_date - timedelta(days=1), end_date=existing_campaign.end_date
        )

        form = AnnouncementCampaignAdminForm(model_to_dict(campaign))

        expected_form_errors = [
            (
                "Il y a déjà une campagne entre ces dates "
                f"({ existing_campaign.start_date } à { existing_campaign.end_date })"
            )
        ]
        assert form.errors["__all__"] == expected_form_errors

        campaign.start_date = existing_campaign.end_date + timedelta(days=1)
        campaign.end_date = existing_campaign.end_date + timedelta(days=2)
        form = AnnouncementCampaignAdminForm(model_to_dict(campaign))
        assert form.is_valid()

    def test_campaign_modify_date_range(self):
        existing_campaign = AnnouncementCampaignFactory()
        existing_campaign.start_date = existing_campaign.start_date - timedelta(days=1)

        form = AnnouncementCampaignAdminForm(model_to_dict(existing_campaign), instance=existing_campaign)
        assert form.is_valid()

    def test_invalid_campaign_max_items(self):
        campaign = AnnouncementCampaignFactory.build(max_items=0)

        form = AnnouncementCampaignAdminForm(model_to_dict(campaign))
        expected_form_errors = ["Impossible de lancer une campagne sans articles."]
        assert form.errors["max_items"] == expected_form_errors


class TestRenderAnnouncementCampaign:
    def test_campaign_rendered_dashboard(self, client, snapshot):
        cache.delete(CACHE_ACTIVE_ANNOUNCEMENT_CAMPAIGN_KEY)
        campaign = AnnouncementCampaignFactory(max_items=3)
        AnnouncementItemFactory(campaign=campaign, title="Item A", description="Item A", priority=0)
        AnnouncementItemFactory(campaign=campaign, title="Item B", description="Item B", priority=1)
        AnnouncementItemFactory(campaign=campaign, title="Item D", description="Item D", priority=3)
        AnnouncementItemFactory(campaign=campaign, title="Item C", description="Item C", priority=2)

        response = client.get(reverse("search:employers_home"))
        assert response.status_code == 200
        content = parse_response_to_soup(response, "#news-modal")
        assert str(content) == snapshot
        assert len(content.select("p")) == 3
        assert "Item D" not in str(content)

    def test_campaign_not_rendered_without_items(self, client):
        AnnouncementCampaignFactory()

        response = client.get(reverse("search:employers_home"))
        assert response.status_code == 200
        content = parse_response_to_soup(response)
        assert len(content.select("#news-modal")) == 0
