import datetime
import io
import operator

import pytest
from django.core import management
from freezegun import freeze_time

from itou.companies.enums import CompanyKind
from tests.companies import factories as companies_factories
from tests.job_applications.factories import JobApplicationFactory


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
        company_2 = companies_factories.CompanyFactory(kind=CompanyKind.EATT)
        management.call_command("move_company_data", from_id=company_1.pk, to_id=company_2.pk, wet_run=True)
        assert company_1.jobs.count() == 0
        assert company_1.members.count() == 0
        assert company_2.jobs.count() == 4
        assert company_2.members.count() == 1

    @pytest.mark.parametrize(
        "preserve,predicate",
        [
            (True, operator.ne),
            (False, operator.eq),
        ],
    )
    def test_preserve_to_company_data(self, preserve, predicate):
        company_1, company_2 = companies_factories.CompanyFactory.create_batch(2, with_informations=True)

        management.call_command(
            "move_company_data",
            from_id=company_1.pk,
            to_id=company_2.pk,
            preserve_to_company_data=preserve,
            wet_run=True,
        )
        company_2.refresh_from_db()
        for field in ["brand", "description", "phone", "coords", "geocoding_score"]:
            assert predicate(getattr(company_2, field), getattr(company_1, field))


def test_update_companies_job_app_score():
    company_1 = companies_factories.CompanyFactory()
    company_2 = JobApplicationFactory(to_company__with_jobs=True).to_company

    assert company_1.job_app_score is None
    assert company_2.job_app_score is None

    stdout = io.StringIO()
    management.call_command("update_companies_job_app_score", stdout=stdout)
    # company_1 did not change (from None to None)
    assert "Updated 1 companies" in stdout.getvalue()

    company_1.refresh_from_db()
    company_2.refresh_from_db()

    assert company_1.job_app_score is None
    assert company_2.job_app_score is not None


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

    management.call_command("update_companies_coords", wet_run=True)
    stdout, stderr = capsys.readouterr()
    assert stderr == ""
    assert stdout.splitlines() == [
        "> about to geolocate count=3 objects without geolocation or with a low " "score.",
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
