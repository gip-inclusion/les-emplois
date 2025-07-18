from datetime import date

import pytest
from django.forms import ModelForm
from django.forms.models import model_to_dict
from django.urls import reverse
from pytest_django.asserts import assertContains, assertNotContains

from itou.communications.models import AnnouncementCampaign
from itou.users.enums import UserKind
from tests.communications.factories import AnnouncementCampaignFactory, AnnouncementItemFactory
from tests.users.factories import ItouStaffFactory, JobSeekerFactory, random_user_kind_factory
from tests.utils.test import parse_response_to_soup, pretty_indented


class TestAnnouncementCampaignValidator:
    class FakeForm(ModelForm):
        class Meta:
            model = AnnouncementCampaign
            fields = "__all__"

    def test_valid_campaign(self):
        expected_form_fields = ["max_items", "start_date", "live"]
        assert list(self.FakeForm().fields.keys()) == expected_form_fields

        form = self.FakeForm(model_to_dict(AnnouncementCampaignFactory.build()))
        assert form.is_valid()

    def test_start_date_conflict(self):
        AnnouncementCampaignFactory(start_date=date(2024, 1, 1))
        campaign = AnnouncementCampaignFactory.build(start_date=date(2024, 1, 20))
        form = self.FakeForm(model_to_dict(campaign))

        expected_form_errors = ["Un objet Campagne d'annonce avec ce champ Mois concerné existe déjà."]
        assert form.errors["start_date"] == expected_form_errors

        campaign.start_date = date(2024, 2, 1)
        form = self.FakeForm(model_to_dict(campaign))
        assert form.is_valid()

    def test_modify_start_date(self):
        existing_campaign = AnnouncementCampaignFactory(start_date=date(2024, 1, 1))
        existing_campaign.start_date = date(2024, 1, 2)

        form = self.FakeForm(model_to_dict(existing_campaign), instance=existing_campaign)
        assert form.is_valid()

    def test_max_items_range(self):
        campaign = AnnouncementCampaignFactory.build(max_items=0)

        form = self.FakeForm(model_to_dict(campaign))
        assert form.errors["max_items"] == ["Assurez-vous que cette valeur est supérieure ou égale à 1."]

        campaign.max_items = 11
        form = self.FakeForm(model_to_dict(campaign))
        assert form.errors["max_items"] == ["Assurez-vous que cette valeur est inférieure ou égale à 10."]

        campaign.max_items = 10
        form = self.FakeForm(model_to_dict(campaign))
        assert form.is_valid()


class TestAnnouncementCampaignAdmin:
    def test_admin_form(self, client):
        campaign = AnnouncementCampaignFactory(with_item=True)

        assert not campaign.items.first().image
        client.force_login(ItouStaffFactory(is_superuser=True))
        response = client.get(
            reverse("admin:communications_announcementcampaign_change", kwargs={"object_id": campaign.pk})
        )
        assert response.status_code == 200


class TestRenderAnnouncementCampaign:
    @pytest.fixture(autouse=True)
    def empty_announcements_cache(self, empty_active_announcements_cache):
        pass

    def test_campaign_rendered_dashboard(self, client, snapshot):
        MODAL_ID = "news-modal"
        campaign = AnnouncementCampaignFactory(max_items=3, start_date=date.today().replace(day=1), live=True)
        user = random_user_kind_factory()
        AnnouncementItemFactory(
            campaign=campaign, title="Item A", description="Item A", priority=0, user_kind_tags=[user.kind]
        )
        AnnouncementItemFactory(
            campaign=campaign, title="Item B", description="Item B", priority=1, user_kind_tags=[user.kind]
        )
        AnnouncementItemFactory(
            campaign=campaign, title="Item D", description="Item D", priority=3, user_kind_tags=[user.kind]
        )
        AnnouncementItemFactory(
            campaign=campaign, title="Item C", description="Item C", priority=2, user_kind_tags=[user.kind]
        )

        response = client.get(reverse("search:employers_home"))
        assertNotContains(response, MODAL_ID)

        client.force_login(user)
        response = client.get(reverse("search:employers_home"))
        assertContains(response, MODAL_ID)

        content = parse_response_to_soup(response, f"#{MODAL_ID}")
        assert pretty_indented(content) == snapshot
        assert len(content.select("li > div")) == 3
        assert "Item D" not in str(content)

    def test_campaign_not_rendered_without_items(self, client):
        AnnouncementCampaignFactory()

        response = client.get(reverse("search:employers_home"))
        assert response.status_code == 200
        content = parse_response_to_soup(response)
        assert len(content.select("#news-modal")) == 0

    def test_campaign_not_rendered_draft(self, client):
        AnnouncementCampaignFactory(live=False, with_item=True)

        response = client.get(reverse("search:employers_home"))
        assert response.status_code == 200
        content = parse_response_to_soup(response)
        assert len(content.select("#news-modal")) == 0

    def test_campaign_rendered_dashboard_for_job_seeker(self, client, snapshot):
        campaign = AnnouncementCampaignFactory(max_items=3, start_date=date.today().replace(day=1), live=True)
        AnnouncementItemFactory(
            campaign=campaign, title="Item A", description="Item A", priority=0, user_kind_tags=[UserKind.JOB_SEEKER]
        )
        AnnouncementItemFactory(
            campaign=campaign,
            title="Item B",
            description="Item B",
            priority=1,
            user_kind_tags=[UserKind.JOB_SEEKER, UserKind.PRESCRIBER],
        )
        AnnouncementItemFactory(campaign=campaign, title="Item D", description="Item D", priority=3, user_kind_tags=[])
        AnnouncementItemFactory(
            campaign=campaign,
            title="Item C",
            description="Item C",
            priority=2,
            user_kind_tags=[UserKind.PRESCRIBER, UserKind.EMPLOYER],
        )

        client.force_login(JobSeekerFactory())
        response = client.get(reverse("search:employers_home"))
        assert response.status_code == 200
        content = parse_response_to_soup(response, "#news-modal")
        assert pretty_indented(content) == snapshot
        assert len(content.select("li > div")) == 3
        assert "Item C" not in str(content)
