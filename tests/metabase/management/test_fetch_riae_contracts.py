import datetime

from django.core import management

from itou.companies.enums import CompanyKind
from itou.companies.models import Contract
from tests.companies.factories import CompanyFactory
from tests.users.factories import JobSeekerFactory


def test_fetch_riae_contracts(mocker, settings):
    settings.METABASE_API_KEY = "metabase-api-key"

    job_seeker = JobSeekerFactory(for_snapshot=True)
    company = CompanyFactory(kind=CompanyKind.ACI)
    convention = company.convention

    mocked_data = [
        {
            "Contrat Date Embauche": "2023-01-01",
            "Contrat Date Fin Contrat": "2023-04-30",
            "Contrat Date Sortie Definitive": None,
            "Contrat ID Ctr": 0,
            "Contrat ID Structure": convention.asp_id,
            "Contrat Mesure Disp Code": "ACIPA_DC",
            "Contrat Parent ID": 0,
            "Emplois Candidat ID": job_seeker.pk,
            "Type Contrat": "initial",
        },  # Ignored contract : unknown Mesure Disp Code
        {
            "Contrat Date Embauche": "2023-01-01",
            "Contrat Date Fin Contrat": "2023-04-30",
            "Contrat Date Sortie Definitive": None,
            "Contrat ID Ctr": 1,
            "Contrat ID Structure": convention.asp_id,
            "Contrat Mesure Disp Code": "ACI_DC",
            "Contrat Parent ID": 1,
            "Emplois Candidat ID": job_seeker.pk,
            "Type Contrat": "initial",
        },  # OK
        {
            "Contrat Date Embauche": "2023-01-01",
            "Contrat Date Fin Contrat": None,
            "Contrat Date Sortie Definitive": "2023-04-30",
            "Contrat ID Ctr": 2,
            "Contrat ID Structure": convention.asp_id,
            "Contrat Mesure Disp Code": "EI_DC",
            "Contrat Parent ID": 2,
            "Emplois Candidat ID": job_seeker.pk,
            "Type Contrat": "initial",
        },  # not match for convention.asp_id + EI kind -> set company=None
        {
            "Contrat Date Embauche": "2023-01-01",
            "Contrat Date Fin Contrat": None,
            "Contrat Date Sortie Definitive": None,
            "Contrat ID Ctr": 3,
            "Contrat ID Structure": convention.asp_id,
            "Contrat Mesure Disp Code": "ACI_DC",
            "Contrat Parent ID": 3,
            "Emplois Candidat ID": 0,
            "Type Contrat": "initial",
        },  # unknown job seeker -> set job_seeker=None
    ]

    mocker.patch(
        "itou.metabase.management.commands.fetch_riae_contracts.Command._get_riae_contracts_data",
        return_value=mocked_data,
    )

    management.call_command("fetch_riae_contracts")

    assert Contract.objects.filter(pk=0).exists() is False

    contract_1 = Contract.objects.get(pk=1)
    assert contract_1.job_seeker_id == job_seeker.pk
    assert contract_1.company_id == company.pk
    assert contract_1.start_date == datetime.date(2023, 1, 1)
    assert contract_1.end_date == datetime.date(2023, 4, 30)
    assert contract_1.details == [mocked_data[1]]

    contract_2 = Contract.objects.get(pk=2)
    assert contract_2.job_seeker_id == job_seeker.pk
    assert contract_2.company_id is None
    assert contract_2.start_date == datetime.date(2023, 1, 1)
    assert contract_2.end_date == datetime.date(2023, 4, 30)
    assert contract_2.details == [mocked_data[2]]

    contract_3 = Contract.objects.get(pk=3)
    assert contract_3.job_seeker_id is None
    assert contract_3.company_id == company.pk
    assert contract_3.start_date == datetime.date(2023, 1, 1)
    assert contract_3.end_date is None
    assert contract_3.details == [mocked_data[3]]

    # Clean old contracts that were removed from metabase
    mocker.patch(
        "itou.metabase.management.commands.fetch_riae_contracts.Command._get_riae_contracts_data",
        return_value=[],
    )

    management.call_command("fetch_riae_contracts")
    assert Contract.objects.exists() is False

    # chain lines with same Contrat Parent ID
    mocked_data = [
        {
            "Contrat Date Embauche": "2023-05-01",
            "Contrat Date Fin Contrat": None,
            "Contrat Date Sortie Definitive": "2023-05-23",
            "Contrat ID Ctr": 2,
            "Contrat ID Structure": convention.asp_id,
            "Contrat Mesure Disp Code": "ACI_DC",
            "Contrat Parent ID": 1,
            "Emplois Candidat ID": job_seeker.pk,
            "Type Contrat": "initial",
        },
        mocked_data[1],
    ]

    mocker.patch(
        "itou.metabase.management.commands.fetch_riae_contracts.Command._get_riae_contracts_data",
        return_value=mocked_data,
    )

    management.call_command("fetch_riae_contracts")

    contract_1 = Contract.objects.get(pk=1)
    assert contract_1.job_seeker_id == job_seeker.pk
    assert contract_1.company_id == company.pk
    assert contract_1.start_date == datetime.date(2023, 1, 1)
    assert contract_1.end_date == datetime.date(2023, 5, 23)
    assert contract_1.details == mocked_data
