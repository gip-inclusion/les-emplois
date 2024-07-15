import uuid
from datetime import date
from unittest import mock

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.forms import ModelForm
from django.forms.models import model_to_dict
from django.urls import reverse

from itou.communications.cache import CACHE_ACTIVE_ANNOUNCEMENTS_KEY
from itou.communications.forms import AnnouncementItemForm
from itou.communications.models import AnnouncementCampaign
from tests.communications.factories import AnnouncementCampaignFactory, AnnouncementItemFactory
from tests.utils.test import TestCase, parse_response_to_soup


class AnnouncementCampaignValidatorTest(TestCase):
    class TestForm(ModelForm):
        class Meta:
            model = AnnouncementCampaign
            fields = "__all__"

    def test_valid_campaign(self):
        expected_form_fields = ["max_items", "start_date", "live"]
        assert list(self.TestForm().fields.keys()) == expected_form_fields

        form = self.TestForm(model_to_dict(AnnouncementCampaignFactory.build()))
        assert form.is_valid()

    def test_start_date_conflict(self):
        AnnouncementCampaignFactory(start_date=date(2024, 1, 1))
        campaign = AnnouncementCampaignFactory.build(start_date=date(2024, 1, 20))
        form = self.TestForm(model_to_dict(campaign))

        expected_form_errors = ["La contrainte « unique_announcement_campaign_month_year » n’est pas respectée."]
        assert form.errors["__all__"] == expected_form_errors

        campaign.start_date = date(2024, 2, 1)
        form = self.TestForm(model_to_dict(campaign))
        assert form.is_valid()

    def test_modify_start_date(self):
        existing_campaign = AnnouncementCampaignFactory(start_date=date(2024, 1, 1))
        existing_campaign.start_date = date(2024, 1, 2)

        form = self.TestForm(model_to_dict(existing_campaign), instance=existing_campaign)
        assert form.is_valid()

    def test_max_items_range(self):
        campaign = AnnouncementCampaignFactory.build(max_items=0)

        form = self.TestForm(model_to_dict(campaign))
        assert form.errors["max_items"] == ["Assurez-vous que cette valeur est supérieure ou égale à 1."]

        campaign.max_items = 11
        form = self.TestForm(model_to_dict(campaign))
        assert form.errors["max_items"] == ["Assurez-vous que cette valeur est inférieure ou égale à 10."]

        campaign.max_items = 10
        form = self.TestForm(model_to_dict(campaign))
        assert form.is_valid()


class TestRenderAnnouncementCampaign:
    def test_campaign_rendered_dashboard(self, client, snapshot):
        cache.delete(CACHE_ACTIVE_ANNOUNCEMENTS_KEY)
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
        cache.delete(CACHE_ACTIVE_ANNOUNCEMENTS_KEY)
        AnnouncementCampaignFactory()

        response = client.get(reverse("search:employers_home"))
        assert response.status_code == 200
        content = parse_response_to_soup(response)
        assert len(content.select("#news-modal")) == 0

    def test_campaign_not_rendered_draft(self, client):
        cache.delete(CACHE_ACTIVE_ANNOUNCEMENTS_KEY)
        AnnouncementCampaignFactory(live=False, with_item=True)

        response = client.get(reverse("search:employers_home"))
        assert response.status_code == 200
        content = parse_response_to_soup(response)
        assert len(content.select("#news-modal")) == 0


class TestAnnouncementItemForm(TestCase):
    def test_form(self):
        assert AnnouncementItemForm(model_to_dict(AnnouncementItemFactory.build())).is_valid()

    @mock.patch("uuid.uuid4", return_value=uuid.UUID("6971c4bb-217f-4e84-b8a0-3f055ed19b72"))
    def test_form_image_upload(self, client):
        form = AnnouncementItemForm({}, instance=AnnouncementItemFactory())
        form.is_valid()

        form.cleaned_data["image"] = SimpleUploadedFile("image.jpg", b"", content_type="image/jpeg")
        image = form.clean_image()

        assert image.name == "6971c4bb-217f-4e84-b8a0-3f055ed19b72.jpg"
