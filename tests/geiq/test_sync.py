import datetime

import pytest
from django.core.exceptions import ImproperlyConfigured

from itou.companies.enums import CompanyKind
from itou.eligibility.models import GEIQAdministrativeCriteria
from itou.geiq import models, sync
from itou.utils.apis import geiq_label
from tests.companies.factories import CompanyFactory
from tests.geiq.factories import (
    GeiqLabelDataFactory,
    ImplementationAssessmentCampaignFactory,
    ImplementationAssessmentFactory,
    SalarieContratLabelDataFactory,
    SalariePreQualificationLabelDataFactory,
)


@pytest.mark.parametrize(
    "periods, year, expected",
    [
        ([], 2024, 0),
        ([("2023-01-01", "2023-01-31")], 2023, 31),
        ([("2023-01-01", "2023-01-31")], 2024, 0),
        ([("2022-01-01", "2024-01-31")], 2023, 365),
        ([("2022-01-01", "2023-01-31"), ("2023-01-15", "2023-01-20")], 2023, 31),
        ([("2022-01-01", "2023-01-31"), ("2023-01-15", "2023-01-20"), ("2023-02-01", "2023-02-20")], 2023, 51),
        ([("2022-01-01", "2023-01-31"), ("2023-01-15", "2023-02-10"), ("2023-02-01", "2023-02-20")], 2023, 51),
    ],
)
def test_nb_days(periods, year, expected):
    parsed_periods = [(datetime.date.fromisoformat(start), datetime.date.fromisoformat(end)) for start, end in periods]
    assert sync._nb_days(parsed_periods, year=year) == expected


def test_sync_assessments_without_configuration(settings):
    settings.API_GEIQ_LABEL_TOKEN = ""
    campaign = ImplementationAssessmentCampaignFactory()
    with pytest.raises(ImproperlyConfigured):
        sync.sync_assessments(campaign)


@pytest.fixture
def label_settings(settings):
    settings.API_GEIQ_LABEL_BASE_URL = "https://geiq.label"
    settings.API_GEIQ_LABEL_TOKEN = "S3cr3t!"
    return settings


def test_sync_assessments(caplog, label_settings, mocker):
    label_settings.GEIQ_ASSESSMENT_CAMPAIGN_POSTCODE_PREFIXES = "29,35"

    mocker.patch.object(
        geiq_label.LabelApiClient,
        "get_all_geiq",
        lambda self: [
            GeiqLabelDataFactory(id=0, siret="", nom="Pas de SIRET"),
            GeiqLabelDataFactory(id=1, siret="1" * 14, nom="SIRET Inconnu"),
            GeiqLabelDataFactory(id=2, siret="2" * 14, nom="SIRET connu et departement OK", cp="29000"),
            GeiqLabelDataFactory(id=3, siret="3" * 14, nom="SIRET connu mais departement KO", cp="75000"),
            GeiqLabelDataFactory(id=4, siret="4" * 14, nom="SIRET connu mais non GEIQ", cp="29000"),
        ],
    )
    siret_OK_and_department_OK = CompanyFactory(kind=CompanyKind.GEIQ, siret="2" * 14)
    siret_OK_and_department_KO = CompanyFactory(kind=CompanyKind.GEIQ, siret="3" * 14)
    siret_OK_but_non_GEIQ = CompanyFactory(kind=CompanyKind.AI, siret="4" * 14)

    campaign = ImplementationAssessmentCampaignFactory()
    creations, updates, deletions = sync.sync_assessments(campaign)
    assert not updates
    assert not deletions
    assert len(creations) == 1
    assert creations[0].label_id == 2
    assert siret_OK_and_department_OK.implementation_assessments.get().label_id == 2
    assert not siret_OK_and_department_KO.implementation_assessments.exists()
    assert not siret_OK_but_non_GEIQ.implementation_assessments.exists()
    assert caplog.messages == [
        "Ignoring geiq='Pas de SIRET' without SIRET",
        "Ignoring geiq='SIRET Inconnu' with unknown SIRET=11111111111111",
        "Ignoring geiq='SIRET connu mais departement KO' since its cp=75000 is not allowed",
        "Ignoring geiq='SIRET connu mais non GEIQ' with unknown SIRET=44444444444444",
        "Label sync will create nb=1 type=bilan d’exécution",
        "Label sync will update nb=0 type=bilan d’exécution",
        "Label sync would delete nb=0 type=bilan d’exécution",
    ]


def test_sync_employee_and_contracts(caplog, label_settings, mocker):
    assessment = ImplementationAssessmentFactory(campaign__year=2023)

    prequal_only = SalariePreQualificationLabelDataFactory(
        salarie__geiq_id=assessment.label_id,
        date_debut="2023-01-01T00:00:00+01:00",
        date_fin="2023-01-31:00:00+01:00",
    )
    contract = SalarieContratLabelDataFactory(
        salarie__geiq_id=assessment.label_id,
        salarie__statuts_prioritaire=[
            {"id": 13, "libelle": "Bénéficiaire du RSA", "libelle_abr": "RSA", "niveau": 1},
        ],
        date_debut="2023-01-01T00:00:00+01:00",
        date_fin="2024-01-31:00:00+01:00",
    )
    contract_with_prequal = SalarieContratLabelDataFactory(
        salarie__geiq_id=assessment.label_id,
        salarie__statuts_prioritaire=[
            {"id": 21, "libelle": "Travailleur handicapé", "libelle_abr": "TH", "niveau": 2},
        ],
        date_debut="2023-01-15:00:00+01:00",
        date_fin="2023-01-31:00:00+01:00",
        date_fin_contrat="2023-01-31:00:00+01:00",
    )
    prequal_of_contract = SalariePreQualificationLabelDataFactory(
        salarie=dict(contract_with_prequal["salarie"]),  # Make a copy since sync function modifies the received data
        date_debut="2022-12-15:00:00+01:00",
        date_fin="2023-01-10:00:00+01:00",
    )
    contract_ending_before_2023 = SalarieContratLabelDataFactory(
        salarie__geiq_id=assessment.label_id,
        date_debut="2022-01-01T00:00:00+01:00",
        date_fin="2023-01-31:00:00+01:00",
        date_fin_contrat="2022-01-31:00:00+01:00",
    )

    def _fake_get_all_contracts(self, geiq_id):
        assert geiq_id == assessment.label_id
        return [dict(contract), dict(contract_with_prequal)]

    def _fake_get_all_prequalifications(self, geiq_id):
        assert geiq_id == assessment.label_id
        return [prequal_only, prequal_of_contract]

    mocker.patch.object(geiq_label.LabelApiClient, "get_all_contracts", _fake_get_all_contracts)
    mocker.patch.object(geiq_label.LabelApiClient, "get_all_prequalifications", _fake_get_all_prequalifications)
    sync.sync_employee_and_contracts(assessment)
    employees = models.Employee.objects.order_by("label_id")
    assert len(employees) == 2
    assert prequal_only["salarie"]["id"] not in {employee.label_id for employee in employees}
    assert contract_ending_before_2023["salarie"]["id"] not in {employee.label_id for employee in employees}
    assert contract["salarie"]["id"] == employees[0].label_id
    assert contract_with_prequal["salarie"]["id"] == employees[1].label_id

    assert employees[0].support_days_nb == 365
    assert employees[0].annex1_nb == 0
    assert employees[0].annex2_level1_nb == 1
    assert employees[0].annex2_level2_nb == 0
    assert employees[0].allowance_amount == 1400

    assert employees[1].support_days_nb == 17 + 10  # contract + prequal
    assert employees[1].annex1_nb == 1
    assert employees[1].annex2_level1_nb == 0
    assert employees[1].annex2_level2_nb == 1
    assert employees[1].allowance_amount == 0  # Since less than 90 days

    assert assessment.last_synced_at is not None

    assert caplog.messages == [
        "Label sync will create nb=2 type=employé",
        "Label sync will update nb=0 type=employé",
        "Label sync will delete nb=0 type=employé",
        "Label sync will create nb=2 type=contrat",
        "Label sync will update nb=0 type=contrat",
        "Label sync will delete nb=0 type=contrat",
        "Label sync will create nb=1 type=préqualification",
        "Label sync will update nb=0 type=préqualification",
        "Label sync will delete nb=0 type=préqualification",
    ]


@pytest.mark.parametrize(
    "api_codes, support_days_nb, annex1_nb, annex2_level1_nb, annex2_level2_nb, allowance_amount",
    [
        (set(), 100, 0, 0, 0, 0),
        ({"TH"}, 100, 1, 0, 1, 814),
        ({"Pers. SH"}, 100, 1, 0, 1, 814),
        ({"Pers. SH", "TH"}, 100, 1, 0, 1, 814),
        ({"RS/PS/DA"}, 100, 0, 0, 1, 0),
        ({"Refug."}, 100, 1, 0, 1, 814),
        ({"Refug.", "RS/PS/DA"}, 100, 1, 0, 1, 814),
        ({"QPV/ZRR"}, 100, 1, 0, 1, 814),
        ({"ZRR"}, 100, 1, 0, 1, 814),
        ({"ZRR", "QPV/ZRR"}, 100, 1, 0, 1, 814),
        ({"QPV", "QPV/ZRR"}, 100, 1, 0, 1, 814),
        ({"Prison"}, 100, 1, 0, 1, 814),
        ({"Detention/MJ"}, 100, 1, 0, 1, 814),
        ({"Detention/MJ", "Prison"}, 100, 1, 0, 1, 814),
        ({"Prescrit"}, 90, 0, 0, 0, 1400),  # Authorized prescriber criteria
        ({"Prescrit"}, 10, 0, 0, 0, 0),  # Less than 90 days
        ({"RSA"}, 100, 0, 1, 0, 1400),
        ({"RSA", "ASS", "AAH"}, 100, 0, 3, 0, 1400),
        ({"TH", "+50"}, 100, 1, 0, 2, 1400),
        ({"TH", "+50", "Pers. SH", "Aucun"}, 100, 1, 0, 2, 1400),
    ],
)
def test_compute_eligibility_fields(
    api_codes, support_days_nb, annex1_nb, annex2_level1_nb, annex2_level2_nb, allowance_amount
):
    code_to_criteria = {
        criteria.api_code: criteria for criteria in GEIQAdministrativeCriteria.objects.exclude(api_code="")
    }
    assert sync._compute_eligibility_fields(api_codes, code_to_criteria, support_days_nb) == {
        "annex1_nb": annex1_nb,
        "annex2_level1_nb": annex2_level1_nb,
        "annex2_level2_nb": annex2_level2_nb,
        "allowance_amount": allowance_amount,
    }
