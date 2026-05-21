import pytest

from itou.geiq_assessments import models, sync
from itou.utils.apis import geiq_label
from tests.geiq.factories import (
    SalarieContratLabelDataFactory,
    SalariePreQualificationLabelDataFactory,
)
from tests.geiq_assessments.factories import AssessmentFactory, EmployeeContractFactory


@pytest.fixture
def label_settings(settings):
    settings.API_GEIQ_LABEL_BASE_URL = "https://geiq.label"
    settings.API_GEIQ_LABEL_TOKEN = "S3cr3t!"
    return settings


def test_sync_employee_and_contracts(caplog, label_settings, mocker):
    assessment = AssessmentFactory(campaign__year=2023, with_main_geiq=True, label_antennas=[])
    prequal_only = SalariePreQualificationLabelDataFactory(
        salarie__geiq_id=assessment.label_geiq_id,
        date_debut="2023-01-01T00:00:00+01:00",
        date_fin="2023-01-31:00:00+01:00",
    )
    contract = SalarieContratLabelDataFactory(
        salarie__geiq_id=assessment.label_geiq_id,
        salarie__montant_aide=1400,
        antenne={"id": 0, "name": "Un Joli GEIQ"},
        date_debut="2023-01-01T00:00:00+01:00",
        date_fin="2024-01-31:00:00+01:00",
    )
    contract_of_antenna = SalarieContratLabelDataFactory(
        salarie__geiq_id=assessment.label_geiq_id,
        antenne={"id": 1, "name": "Antenne 1"},
        date_debut="2023-01-01T00:00:00+01:00",
        date_fin="2024-01-31:00:00+01:00",
    )
    contract_with_prequal = SalarieContratLabelDataFactory(
        salarie__geiq_id=assessment.label_geiq_id,
        salarie__montant_aide=814,
        antenne={"id": 0, "name": "Un Joli GEIQ"},
        date_debut="2023-01-15:00:00+01:00",
        date_fin="2023-01-31:00:00+01:00",  # Contract duration is less than 3 months
        date_fin_contrat="2023-01-31:00:00+01:00",
    )
    prequal_of_contract = SalariePreQualificationLabelDataFactory(
        salarie=dict(contract_with_prequal["salarie"]),  # Make a copy since sync function modifies the received data
        date_debut="2022-12-15:00:00+01:00",
        date_fin="2023-01-10:00:00+01:00",
    )
    contract_ending_before_2023 = SalarieContratLabelDataFactory(
        salarie__geiq_id=assessment.label_geiq_id,
        date_debut="2022-01-01T00:00:00+01:00",
        date_fin="2023-01-31:00:00+01:00",
        date_fin_contrat="2022-01-31:00:00+01:00",
    )
    contract_without_allowance = SalarieContratLabelDataFactory(
        salarie__geiq_id=assessment.label_geiq_id,
        salarie__montant_aide=0,
        antenne={"id": 0, "name": "Un Joli GEIQ"},
        date_debut="2023-01-01T00:00:00+01:00",
        date_fin="2024-01-31:00:00+01:00",
    )

    EmployeeContractFactory(
        allowance_requested=True,
        allowance_granted=True,
        employee__label_id=contract["salarie"]["id"],
        employee__assessment__label_geiq_id=assessment.label_geiq_id,
        employee__assessment__campaign__year=2022,
    )

    EmployeeContractFactory(
        allowance_requested=True,
        allowance_granted=True,
        employee__label_id=contract_with_prequal["salarie"]["id"],
        employee__assessment__label_geiq_id=assessment.label_geiq_id,
        employee__assessment__campaign__year=2021,
    )

    def _fake_get_all_contracts(self, geiq_id, date_fin=None):
        assert geiq_id == assessment.label_geiq_id
        return [dict(c) for c in (contract, contract_with_prequal, contract_of_antenna, contract_without_allowance)]

    def _fake_get_all_prequalifications(self, geiq_id):
        assert geiq_id == assessment.label_geiq_id
        return [prequal_only, prequal_of_contract]

    FAKE_LABEL_RATES = {
        "geiq_id": assessment.label_geiq_id,
        "taux_sortie_emploi": "82.8",
        "taux_rupture_periode_essai": "",
        "taux_sortie_emploi_durable": "51.7",
        "taux_obtention_qualification": "91.4",
        "taux_rupture_hors_periode_essai": "14.3",
    }

    def _fake_get_taux_geiq(self, geiq_id):
        assert geiq_id == assessment.label_geiq_id
        return [FAKE_LABEL_RATES]

    mocker.patch.object(geiq_label.LabelApiClient, "get_all_contracts", _fake_get_all_contracts)
    mocker.patch.object(geiq_label.LabelApiClient, "get_all_prequalifications", _fake_get_all_prequalifications)
    mocker.patch.object(geiq_label.LabelApiClient, "get_taux_geiq", _fake_get_taux_geiq)
    sync.sync_employee_and_contracts(assessment)
    employees = models.Employee.objects.filter(assessment=assessment).order_by("label_id")
    assert len(employees) == 3
    assert prequal_only["salarie"]["id"] not in {employee.label_id for employee in employees}
    assert contract_ending_before_2023["salarie"]["id"] not in {employee.label_id for employee in employees}
    assert contract["salarie"]["id"] == employees[0].label_id
    assert contract_with_prequal["salarie"]["id"] == employees[1].label_id

    assert employees[0].label_id == contract["salarie"]["id"]
    assert employees[0].allowance_amount == 1400
    assert employees[0].allowance_granted_previous_year is True
    contract0 = employees[0].contracts.first()
    assert contract0.nb_days_in_campaign_year == 365
    assert contract0.allowance_requested is True
    assert contract0.allowance_granted is False
    assert employees[1].label_id == contract_with_prequal["salarie"]["id"]
    assert employees[1].allowance_amount == 814
    assert employees[1].allowance_granted_previous_year is False
    contract1 = employees[1].contracts.first()
    assert contract1.nb_days_in_campaign_year == 17
    assert contract1.allowance_requested is False  # Since less than 90 days
    assert contract1.allowance_granted is False
    assert employees[2].allowance_amount == 0
    assert employees[2].allowance_granted_previous_year is False
    contract2 = employees[2].contracts.first()
    assert contract2.allowance_requested is False  # Since no potential allowance
    assert contract2.allowance_granted is False

    assessment.refresh_from_db()
    assert assessment.contracts_synced_at is not None
    assert assessment.label_rates == FAKE_LABEL_RATES
    assert assessment.employee_nb == 3

    assert caplog.messages == [
        "Label sync will create nb=3 type=employé",
        "Label sync will update nb=0 type=employé",
        "Label sync will delete nb=0 type=employé",
        "Label sync will create nb=3 type=contrat",
        "Label sync will update nb=0 type=contrat",
        "Label sync will delete nb=0 type=contrat",
        "Label sync will create nb=1 type=préqualification",
        "Label sync will update nb=0 type=préqualification",
        "Label sync will delete nb=0 type=préqualification",
    ]
