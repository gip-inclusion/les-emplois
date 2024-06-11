import pytest
from django.contrib import messages
from django.contrib.admin import helpers
from django.urls import reverse
from pytest_django.asserts import assertMessages

from itou.companies.enums import CompanyKind
from itou.utils.apis import geiq_label
from tests.companies.factories import CompanyFactory
from tests.geiq.factories import GeiqLabelDataFactory, ImplementationAssessmentCampaignFactory


def test_sync_assessments_without_conf(admin_client, settings):
    settings.API_GEIQ_LABEL_TOKEN = ""
    campaign = ImplementationAssessmentCampaignFactory()

    response = admin_client.post(
        reverse("admin:geiq_implementationassessmentcampaign_changelist"),
        {
            "action": "sync_assessments",
            helpers.ACTION_CHECKBOX_NAME: [campaign.pk],
        },
    )

    assertMessages(
        response,
        [messages.Message(messages.ERROR, "Synchronisation impossible avec Label: configuration incomplète")],
    )


@pytest.fixture
def label_settings(settings):
    settings.API_GEIQ_LABEL_BASE_URL = "https://geiq.label"
    settings.API_GEIQ_LABEL_TOKEN = "S3cr3t!"
    return settings


def test_sync_assessments_http_error(admin_client, label_settings, respx_mock):
    respx_mock.get(f"{label_settings.API_GEIQ_LABEL_BASE_URL}/rest/GeiqFFGeiq?sort=geiq.id&n=100&p=1").respond(400)
    campaign = ImplementationAssessmentCampaignFactory()

    response = admin_client.post(
        reverse("admin:geiq_implementationassessmentcampaign_changelist"),
        {
            "action": "sync_assessments",
            helpers.ACTION_CHECKBOX_NAME: [campaign.pk],
        },
    )

    assertMessages(
        response,
        [messages.Message(messages.ERROR, f"Erreur lors de la synchronisation de la campagne {campaign} avec Label")],
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
    campaign = ImplementationAssessmentCampaignFactory(year=2023)

    response = admin_client.post(
        reverse("admin:geiq_implementationassessmentcampaign_changelist"),
        {
            "action": "sync_assessments",
            helpers.ACTION_CHECKBOX_NAME: [campaign.pk],
        },
    )

    assertMessages(
        response,
        [
            messages.Message(messages.SUCCESS, "Les bilans de l’année 2023 ont été synchronisés."),
            messages.Message(messages.SUCCESS, "1 bilan créé."),
        ],
    )
    assert campaign.implementation_assessments.count() == 1
