import datetime
import io
import operator

import pytest
from dateutil.relativedelta import relativedelta
from django.contrib.gis.geos import Point
from django.core import management
from django.utils import timezone
from freezegun import freeze_time

from itou.companies.enums import CompanyKind
from itou.companies.models import Company, JobDescription
from tests.companies import factories as companies_factories
from tests.eligibility import factories as eligibility_factories
from tests.job_applications.factories import JobApplicationFactory
from tests.jobs.factories import create_test_romes_and_appellations
from tests.siae_evaluations.factories import EvaluatedSiaeFactory


class TestMoveCompanyData:
    def test_uses_wet_run(self):
        company_1 = companies_factories.CompanyWithMembershipAndJobsFactory()
        company_2 = companies_factories.CompanyFactory()
        management.call_command("move_company_data", from_id=company_1.pk, to_id=company_2.pk)
        assert company_1.jobs.count() == 4
        assert company_1.members.count() == 1
        assert company_2.jobs.count() == 0
        assert company_2.members.count() == 0

        management.call_command("move_company_data", from_id=company_1.pk, to_id=company_2.pk, wet_run=True)
        assert company_1.jobs.count() == 0
        assert company_1.members.count() == 0
        assert company_2.jobs.count() == 4
        assert company_2.members.count() == 1

    def test_does_not_stop_if_kind_is_different(self):
        company_1 = companies_factories.CompanyWithMembershipAndJobsFactory(kind=CompanyKind.ACI)
        company_2 = companies_factories.CompanyFactory(kind=CompanyKind.EI)
        management.call_command("move_company_data", from_id=company_1.pk, to_id=company_2.pk, wet_run=True)
        assert company_1.jobs.count() == 0
        assert company_1.members.count() == 0
        assert company_2.jobs.count() == 4
        assert company_2.members.count() == 1

    def test_prevent_move_outside_iae(self, capsys):
        company_1 = eligibility_factories.IAEEligibilityDiagnosisFactory(from_employer=True).author_siae
        company_2 = companies_factories.CompanyFactory(kind=CompanyKind.EATT)
        management.call_command("move_company_data", from_id=company_1.pk, to_id=company_2.pk, wet_run=True)
        assert company_1.members.count() == 1
        assert company_2.members.count() == 0
        _stdout, stderr = capsys.readouterr()
        assert stderr == "Objets impossibles à transférer hors-IAE: Diagnostics IAE créés\n"

    def test_prevent_move_outside_geiq(self, capsys):
        company_1 = eligibility_factories.GEIQEligibilityDiagnosisFactory(from_employer=True).author_geiq
        company_2 = companies_factories.CompanyFactory(kind=CompanyKind.EATT)
        management.call_command("move_company_data", from_id=company_1.pk, to_id=company_2.pk, wet_run=True)
        assert company_1.members.count() == 2
        assert company_2.members.count() == 0
        _stdout, stderr = capsys.readouterr()
        assert stderr == "Objets impossibles à transférer hors-GEIQ: Diagnostics GEIQ créés\n"

    @pytest.mark.parametrize(
        "preserve,predicate",
        [
            (True, operator.ne),
            (False, operator.eq),
        ],
    )
    def test_preserve_to_company_data(self, preserve, predicate):
        company_1 = companies_factories.CompanyFactory.create(
            brand="COMPANY 1",
            description="COMPANY 1",
            phone="0000000001",
            coords=Point(-2.3140436, 47.3618584),
            geocoding_score=0.1,
            is_searchable=True,
        )
        company_2 = companies_factories.CompanyFactory.create(
            brand="COMPANY 2",
            description="COMPANY 2",
            phone="0000000002",
            coords=Point(-2.8186843, 47.657641),
            geocoding_score=0.2,
            is_searchable=False,
        )

        management.call_command(
            "move_company_data",
            from_id=company_1.pk,
            to_id=company_2.pk,
            preserve_to_company_data=preserve,
            wet_run=True,
        )
        company_2.refresh_from_db()
        for field in ["brand", "description", "phone", "is_searchable"]:
            assert predicate(getattr(company_2, field), getattr(company_1, field))
        # In move_all_data, the from_company should not appear in search results anymore
        # and its coords are erased
        company_1.refresh_from_db()
        assert company_1.is_searchable is False

    def test_prevent_move_with_siae_evaluations(self, capsys):
        company1 = EvaluatedSiaeFactory().siae
        company2 = companies_factories.CompanyFactory()

        management.call_command("move_company_data", from_id=company1.pk, to_id=company2.pk, wet_run=True)
        _stdout, stderr = capsys.readouterr()
        assert stderr == (
            f"Impossible de transférer les objets de l'entreprise ID={company1.pk}: "
            "il y a un contrôle a posteriori lié. Vérifiez avec l'équipe support.\n"
        )

        management.call_command(
            "move_company_data", from_id=company1.pk, to_id=company2.pk, wet_run=True, ignore_siae_evaluations=True
        )
        stdout, stderr = capsys.readouterr()
        assert stderr == ""
        assert f"MOVE DATA OF company.id={company1.pk}" in stdout
        assert f"INTO company.id={company2.pk}" in stdout


def test_update_companies_job_app_score(caplog):
    company_1 = companies_factories.CompanyFactory()
    company_2 = JobApplicationFactory(to_company__with_jobs=True).to_company

    assert company_1.job_app_score == Company.MAX_DEFAULT_JOB_APP_SCORE
    assert company_2.job_app_score == Company.MAX_DEFAULT_JOB_APP_SCORE

    stdout = io.StringIO()
    management.call_command("update_companies_job_app_score")
    assert caplog.messages[0] == "Updated 2 companies"

    company_1.refresh_from_db()
    company_2.refresh_from_db()

    assert company_1.job_app_score != Company.MAX_DEFAULT_JOB_APP_SCORE
    assert company_1.job_app_score == company_1.job_applications_received.count()
    assert company_2.job_app_score != Company.MAX_DEFAULT_JOB_APP_SCORE
    assert company_2.spontaneous_applications_open_since is not None
    assert company_2.job_app_score == company_2.job_applications_received.count() / (
        company_2.job_description_through.count() + 1
    )

    # Deleting job descriptions should bring score back to job_applications_received.count().
    for jd in company_2.job_description_through.all():
        jd.delete()
    caplog.clear()
    management.call_command("update_companies_job_app_score", stdout=stdout)
    # company_2 changed
    assert caplog.messages[0] == "Updated 1 companies"

    company_1.refresh_from_db()
    company_2.refresh_from_db()

    assert company_1.job_app_score != Company.MAX_DEFAULT_JOB_APP_SCORE
    assert company_1.job_app_score == company_1.job_applications_received.count()
    assert company_2.job_app_score != Company.MAX_DEFAULT_JOB_APP_SCORE
    assert company_2.job_app_score == company_2.job_applications_received.count()


@freeze_time("2023-05-01")
def test_update_companies_coords(settings, capsys, respx_mock):
    company_1 = companies_factories.CompanyFactory(
        coords="POINT (2.387311 48.917735)", geocoding_score=0.65
    )  # score too low
    company_2 = companies_factories.CompanyFactory(coords=None, geocoding_score=0.9)  # no coords
    company_3 = companies_factories.CompanyFactory(
        coords="POINT (5.43567 12.123876)", geocoding_score=0.76
    )  # score too low
    companies_factories.CompanyFactory(coords="POINT (5.43567 12.123876)", geocoding_score=0.9)

    settings.API_BAN_BASE_URL = "https://geo.foo"
    respx_mock.post("https://geo.foo/search/csv/").respond(
        200,
        text=(
            "id;result_label;result_score;latitude;longitude\n"
            "42;7 rue de Laroche;0.77;42.42;13.13\n"  # score is lower than the minimum fiability score
            "12;5 rue Bigot;0.32;42.42;13.13\n"  # score is lower than the current one
            "78;9 avenue Delorme 92220 Boulogne;0.83;42.42;13.13\n"  # score is higher than current one
        ),
    )

    management.call_command("update_companies_coords", wet_run=True, verbosity=2)
    stdout, stderr = capsys.readouterr()
    assert stderr == ""
    assert stdout.splitlines() == [
        "> about to geolocate count=3 objects without geolocation or with a low score.",
        "> count=3 of these have an address and a post code.",
        "API result score=0.77 label='7 rue de Laroche' "
        f"searched_address='{company_1.address_line_1} {company_1.post_code}' object_pk={company_1.pk}",
        "API result score=0.32 label='5 rue Bigot' "
        f"searched_address='{company_2.address_line_1} {company_2.post_code}' object_pk={company_2.pk}",
        "API result score=0.83 label='9 avenue Delorme 92220 Boulogne' "
        f"searched_address='{company_3.address_line_1} {company_3.post_code}' object_pk={company_3.pk}",
        "> count=1 companies geolocated with a high score.",
    ]

    company_3.refresh_from_db()
    assert company_3.ban_api_resolved_address == "9 avenue Delorme 92220 Boulogne"
    assert company_3.geocoding_updated_at == datetime.datetime(2023, 5, 1, 0, 0, tzinfo=datetime.UTC)
    assert company_3.geocoding_score == 0.83
    assert company_3.coords.x == 13.13
    assert company_3.coords.y == 42.42


def test_deactivate_old_job_description():
    create_test_romes_and_appellations(("N1101",))
    companies_factories.JobDescriptionFactory(
        last_employer_update_at=timezone.now() - relativedelta(years=1),
        location=None,
    )
    companies_factories.JobDescriptionFactory(
        last_employer_update_at=None,
        location=None,
    )
    recently_updated_job_description = companies_factories.JobDescriptionFactory(
        last_employer_update_at=timezone.now() - relativedelta(years=1) + relativedelta(days=1),
        location=None,
    )
    assert JobDescription.objects.active().count() == 3
    management.call_command("deactivate_old_job_descriptions")
    assert JobDescription.objects.active().get() == recently_updated_job_description
