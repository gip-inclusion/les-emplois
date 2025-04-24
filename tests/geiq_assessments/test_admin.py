import pytest
from django.contrib import messages
from django.contrib.admin import helpers
from django.urls import reverse
from pytest_django.asserts import assertMessages

from itou.companies.enums import CompanyKind
from itou.utils.apis import geiq_label
from tests.companies.factories import CompanyFactory
from tests.geiq.factories import GeiqLabelDataFactory
from tests.geiq_assessments.factories import AssessmentCampaignFactory


def test_sync_assessments_without_conf(admin_client, settings):
    settings.API_GEIQ_LABEL_TOKEN = ""
    campaign = AssessmentCampaignFactory()

    response = admin_client.post(
        reverse("admin:geiq_assessments_assessmentcampaign_changelist"),
        {
            "action": "download_label_infos",
            helpers.ACTION_CHECKBOX_NAME: [campaign.pk],
        },
    )

    assertMessages(
        response,
        [messages.Message(messages.ERROR, "Synchronisation impossible avec label: configuration incomplète")],
    )


@pytest.fixture
def label_settings(settings):
    settings.API_GEIQ_LABEL_BASE_URL = "https://geiq.label"
    settings.API_GEIQ_LABEL_TOKEN = "S3cr3t!"
    return settings


def test_sync_assessments_http_error(admin_client, label_settings, respx_mock):
    respx_mock.get(f"{label_settings.API_GEIQ_LABEL_BASE_URL}/rest/Geiq?sort=geiq.id&n=100&p=1").respond(400)
    campaign = AssessmentCampaignFactory()

    response = admin_client.post(
        reverse("admin:geiq_assessments_assessmentcampaign_changelist"),
        {
            "action": "download_label_infos",
            helpers.ACTION_CHECKBOX_NAME: [campaign.pk],
        },
    )

    assertMessages(
        response,
        [
            messages.Message(
                messages.ERROR, f"Erreur lors de la synchronisation de la campagne {campaign.year} avec label"
            )
        ],
    )


def test_sync_assessments_all_good(admin_client, label_settings, mocker):
    geiq = CompanyFactory(kind=CompanyKind.GEIQ)
    mocker.patch.object(
        geiq_label.LabelApiClient,
        "get_all_geiq",
        lambda self: [
            GeiqLabelDataFactory(siret=geiq.siret),
        ],
    )
    campaign = AssessmentCampaignFactory(year=2024)
    assert not hasattr(campaign, "label_infos")

    response = admin_client.post(
        reverse("admin:geiq_assessments_assessmentcampaign_changelist"),
        {
            "action": "download_label_infos",
            helpers.ACTION_CHECKBOX_NAME: [campaign.pk],
        },
    )

    assertMessages(
        response,
        [
            messages.Message(messages.SUCCESS, "Les informations label de la campagne 2024 ont été récupérées."),
        ],
    )
    campaign.refresh_from_db()
    assert campaign.label_infos
    assert len(campaign.label_infos.data) == 1
    assert campaign.label_infos.data[0]["siret"] == geiq.siret
