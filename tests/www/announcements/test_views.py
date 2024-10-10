import pytest
from django.urls import reverse
from pytest_django.asserts import assertContains, assertRedirects

from itou.users.enums import UserKind
from itou.utils.constants import ITOU_HELP_CENTER_URL
from tests.communications.factories import AnnouncementCampaignFactory, AnnouncementItemFactory
from tests.users.factories import EmployerFactory, JobSeekerFactory, PrescriberFactory
from tests.utils.test import parse_response_to_soup


class TestNewsRender:
    @pytest.fixture(autouse=True)
    def empty_announcements_cache(self, empty_active_announcements_cache):
        pass

    def _assert_all_items_rendered(self, response, *campaigns):
        assert response.status_code == 200

        for i, rendered_campaign in enumerate(response.context["news_page"]):
            rendered_items = rendered_campaign.items.all()
            assert list(rendered_items) == list(campaigns[i].items.all())

    def test_all_news_rendered_html(self, client, snapshot):
        campaign = AnnouncementCampaignFactory(for_snapshot=True, with_items_for_every_user_kind=True)

        user = EmployerFactory(with_company=True)
        client.force_login(user)
        response = client.get(reverse("announcements:news"))

        self._assert_all_items_rendered(response, campaign)

        # rendering in HTML
        content = parse_response_to_soup(response, ".s-section__container")
        assert str(content) == snapshot

    def test_announcements_anonymous_user(self, client):
        campaign = AnnouncementCampaignFactory(for_snapshot=True, with_items_for_every_user_kind=True)

        response = client.get(reverse("announcements:news"))
        self._assert_all_items_rendered(response, campaign)

    def test_campaign_items_filtered_on_user_type(self, client):
        campaign = AnnouncementCampaignFactory(with_items_for_every_user_kind=True)
        url = reverse("announcements:news")

        # prescriber receives all items
        user = PrescriberFactory()
        client.force_login(user)
        response = client.get(url)
        self._assert_all_items_rendered(response, campaign)

        # candidates only receive news relating to them
        assert campaign.items.exclude(user_kind_tags__contains=[UserKind.JOB_SEEKER]).exists()
        client.force_login(JobSeekerFactory())
        response = client.get(url)
        assert response.status_code == 200

        items = response.context["news_page"][0].items
        for tags in items.values_list("user_kind_tags", flat=True):
            assert len(tags) == 0 or UserKind.JOB_SEEKER.value in tags
        assert items.count() < campaign.items.count()
        assert items.count() == response.context["news_page"][0].count_items

    def test_only_live_campaigns_rendered(self, client):
        campaign = AnnouncementCampaignFactory(with_item=True)
        AnnouncementCampaignFactory(with_item=True, live=False)
        AnnouncementCampaignFactory(live=True)  # no item

        response = client.get(reverse("announcements:news"))
        assert response.status_code == 200
        assert len(response.context["news_page"]) == 1
        assert response.context["news_page"][0] == campaign

    def test_pagination(self, client):
        items_per_page = 12
        total_items = items_per_page + 2
        campaigns = AnnouncementCampaignFactory.create_batch(total_items, with_items_for_every_user_kind=True)

        url = reverse("announcements:news")
        second_page_url = f"{url}?page=2"

        response = client.get(url)
        assertContains(response, second_page_url)
        assert len(response.context["news_page"]) == items_per_page

        response = client.get(second_page_url)
        assert response.status_code == 200
        expected_len = total_items - items_per_page
        assert len(response.context["news_page"]) == expected_len
        paged_campaigns = campaigns[items_per_page : (items_per_page + expected_len)]
        self._assert_all_items_rendered(response, *paged_campaigns)

    def test_none_exists(self, client):
        expected_redirect_url = f"{ ITOU_HELP_CENTER_URL }/categories/25225629682321--Nouveaut%C3%A9s"

        client.force_login(PrescriberFactory())
        url = reverse("announcements:news")
        assertRedirects(client.get(url), expected_redirect_url, fetch_redirect_response=False)

        AnnouncementCampaignFactory(live=False, with_item=True)
        assertRedirects(client.get(url), expected_redirect_url, fetch_redirect_response=False)

        # it's also possible that there are live campaigns without content for my user kind
        AnnouncementItemFactory(user_kind_tags=[UserKind.PRESCRIBER])
        client.force_login(JobSeekerFactory())
        assertRedirects(client.get(url), expected_redirect_url, fetch_redirect_response=False)
